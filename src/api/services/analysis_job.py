import asyncio
import time
from typing import Optional

from src.agent.subagents.analyst.charts import Insight
from src.api.services.analyze import AnalyzeService
from src.api.services.job import JobData, JobRepository, JobType
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

# Upper bound on the analytics pull. The request waits for the analysis, so
# this must stay comfortably below the infrastructure's gateway/idle timeout
# (typically 60s) — otherwise the client sees a dropped connection instead of
# a failed job.
ANALYZE_TIMEOUT_SECONDS = 50.0


class AnalysisJobRunner:
    """Runs an analysis synchronously and persists the outcome in one go.

    Unlike the previous fire-and-forget background task, `run` returns only
    after the job reached a terminal state. Success writes the job, insight,
    charts and resource link in a single transaction; there is no intermediate
    `pending`/`running` state to strand if the process dies mid-analysis —
    nothing is persisted until the outcome is known.
    """

    def __init__(
        self,
        service: AnalyzeService,
        repo: JobRepository,
        timeout_seconds: float = ANALYZE_TIMEOUT_SECONDS,
    ):
        self._service = service
        self._repo = repo
        self._timeout_seconds = timeout_seconds

    async def run(
        self,
        user_id: str,
        aois: list[dict],
        dataset_id: int,
        start_date: str,
        end_date: str,
        thread_id: Optional[str] = None,
    ) -> JobData:
        logger.info(
            "analysis_job_started",
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
        except TimeoutError:
            logger.error(
                "analysis_job_timed_out",
                severity="high",
                user_id=user_id,
                dataset_id=dataset_id,
                timeout_seconds=self._timeout_seconds,
            )
            return await self._fail(user_id, thread_id)
        except Exception:
            logger.exception(
                "analysis_job_errored",
                severity="high",
                user_id=user_id,
                dataset_id=dataset_id,
            )
            return await self._fail(user_id, thread_id)

        duration_ms = round((time.perf_counter() - started_at) * 1000)

        if not result.data.success:
            logger.error(
                "analysis_job_failed",
                severity="high",
                user_id=user_id,
                duration_ms=duration_ms,
                error_details=result.data.message,
            )
            return await self._fail(user_id, thread_id)

        # Charts only, no narrative: this job doesn't run the LLM text
        # generation step.
        insight = Insight(charts=result.charts)

        # A persistence error propagates to the caller (router → 500): the
        # transaction rolled back atomically, so nothing partial exists and a
        # retry starts clean.
        job = await self._repo.create_completed_job(
            user_id=user_id,
            thread_id=thread_id,
            type=JobType.ANALYSIS,
            insight=insight,
        )
        logger.info(
            "analysis_job_completed",
            job_id=str(job.id),
            user_id=user_id,
            duration_ms=duration_ms,
        )
        return job

    async def _fail(self, user_id: str, thread_id: Optional[str]) -> JobData:
        return await self._repo.create_failed_job(
            user_id=user_id,
            thread_id=thread_id,
            type=JobType.ANALYSIS,
        )
