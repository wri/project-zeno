"""Synchronous analysis execution for `/api/analyze`."""

import asyncio
import time
from typing import Awaitable, Callable, Optional

from src.agent.subagents.analyst.charts import Insight
from src.api.repositories.insight_writer import persist_insight
from src.api.services.analyze import AnalyzeService
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

# Upper bound on the analytics pull. The request waits for the analysis, so
# this must stay comfortably below the infrastructure's gateway/idle timeout
# (typically 60s) — otherwise the client sees a dropped connection instead of
# a clean error response.
ANALYZE_TIMEOUT_SECONDS = 50.0

PersistInsight = Callable[..., Awaitable[str]]


class AnalysisError(Exception):
    """The analysis did not produce a result (upstream failure or error)."""


class AnalysisTimeoutError(AnalysisError):
    """The analytics pull exceeded the request-cycle time budget."""


class AnalysisRunner:
    """Runs an analysis synchronously and persists the resulting insight.

    Mirrors the agent/chat path (`Analyst.analyze`): success persists an
    insight with its charts via `persist_insight` and returns the insight id;
    failure raises without persisting anything, surfacing to the client as an
    HTTP error — the same philosophy as a failed chart-generation turn in
    chat, where nothing is persisted either.
    """

    def __init__(
        self,
        service: AnalyzeService,
        persist: PersistInsight = persist_insight,
        timeout_seconds: float = ANALYZE_TIMEOUT_SECONDS,
    ):
        self._service = service
        self._persist = persist
        self._timeout_seconds = timeout_seconds

    async def run(
        self,
        user_id: str,
        aois: list[dict],
        dataset_id: int,
        start_date: str,
        end_date: str,
        thread_id: Optional[str] = None,
    ) -> str:
        """Run the analysis and return the persisted insight's id."""
        logger.info(
            "analysis_started",
            user_id=user_id,
            dataset_id=dataset_id,
            start_date=start_date,
            end_date=end_date,
        )

        started_at = time.perf_counter()
        try:
            async with asyncio.timeout(self._timeout_seconds):
                result = await self._service.analyze(
                    aois=aois,
                    dataset_id=dataset_id,
                    start_date=start_date,
                    end_date=end_date,
                )
        except TimeoutError as exc:
            logger.error(
                "analysis_timed_out",
                severity="high",
                user_id=user_id,
                dataset_id=dataset_id,
                timeout_seconds=self._timeout_seconds,
            )
            raise AnalysisTimeoutError("Analysis timed out") from exc
        except Exception as exc:
            logger.exception(
                "analysis_errored",
                severity="high",
                user_id=user_id,
                dataset_id=dataset_id,
            )
            raise AnalysisError("Analysis failed") from exc

        duration_ms = round((time.perf_counter() - started_at) * 1000)

        if not result.data.success:
            logger.error(
                "analysis_failed",
                severity="high",
                user_id=user_id,
                duration_ms=duration_ms,
                error_details=result.data.message,
            )
            raise AnalysisError("Analysis failed")

        # Charts only, no narrative: this path doesn't run the LLM text
        # generation step.
        insight = Insight(charts=result.charts)

        # A persistence error propagates as-is (router → 500): the transaction
        # rolled back atomically, so nothing partial exists and a retry starts
        # clean.
        insight_id = await self._persist(
            insight,
            user_id=user_id,
            thread_id=thread_id or "",
        )
        logger.info(
            "analysis_completed",
            insight_id=insight_id,
            user_id=user_id,
            duration_ms=duration_ms,
        )
        return insight_id
