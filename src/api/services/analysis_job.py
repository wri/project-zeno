import time
from typing import Optional
from uuid import UUID

from src.agent.subagents.analyst.charts import InsightBundle
from src.api.services.analyze import AnalyzeService
from src.api.services.job import JobRepository, JobStatus
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class AnalysisJobRunner:
    def __init__(self, service: AnalyzeService, repo: JobRepository):
        self._service = service
        self._repo = repo

    async def run(
        self,
        job_id: UUID,
        user_id: str,
        aois: list[dict],
        dataset_id: int,
        start_date: str,
        end_date: str,
        thread_id: Optional[str] = None,
    ) -> None:
        await self._repo.update_job_status(job_id, JobStatus.RUNNING)
        logger.info(
            "analysis_job_started",
            job_id=str(job_id),
            user_id=user_id,
            dataset_id=dataset_id,
            start_date=start_date,
            end_date=end_date,
        )

        started_at = time.perf_counter()
        try:
            result = await self._service.analyze(
                aois=aois,
                dataset_id=dataset_id,
                start_date=start_date,
                end_date=end_date,
            )
            duration_ms = round((time.perf_counter() - started_at) * 1000)

            if not result.data.success:
                await self._repo.update_job_status(job_id, JobStatus.FAILED)
                logger.error(
                    "analysis_job_failed",
                    severity="high",
                    job_id=str(job_id),
                    user_id=user_id,
                    duration_ms=duration_ms,
                    error_details=result.data.message,
                )
                return

            # Charts only, no narrative: this job doesn't run the LLM text
            # generation step.
            bundle = InsightBundle(charts=result.charts)

            await self._repo.create_insight_resource(
                job_id=job_id,
                user_id=user_id,
                thread_id=thread_id,
                bundle=bundle,
            )

            await self._repo.update_job_status(job_id, JobStatus.COMPLETED)
            logger.info(
                "analysis_job_completed",
                job_id=str(job_id),
                user_id=user_id,
                duration_ms=duration_ms,
            )
        except Exception:
            # Fire-and-forget BackgroundTask: an unhandled exception would leave
            # the job stuck in RUNNING, so mark it FAILED instead. (May leave an
            # InsightOrm row with no JobResource pointing at it — harmless dead
            # data, not something that blocks the job or future requests.)
            await self._repo.update_job_status(job_id, JobStatus.FAILED)
            logger.exception(
                "analysis_job_errored",
                severity="high",
                job_id=str(job_id),
                user_id=user_id,
            )
