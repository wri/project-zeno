from typing import Optional
from uuid import UUID

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

        result = await self._service.analyze(
            aois=aois,
            dataset_id=dataset_id,
            start_date=start_date,
            end_date=end_date,
        )

        if not result.data.success:
            await self._repo.update_job_status(job_id, JobStatus.FAILED)
            logger.error(
                "analysis_job_failed",
                severity="high",
                job_id=str(job_id),
                user_id=user_id,
                error_details=result.data.message,
            )
            return

        await self._repo.create_insight_resource(
            job_id=job_id,
            user_id=user_id,
            thread_id=thread_id,
            charts=result.charts or [],
        )
        await self._repo.update_job_status(job_id, JobStatus.COMPLETED)
        logger.info(
            "analysis_job_completed",
            job_id=str(job_id),
            user_id=user_id,
        )
