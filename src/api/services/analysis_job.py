from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional
from uuid import UUID

from src.api.services.analyze import AnalyzeService


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobType(str, Enum):
    ANALYSIS = "analysis"


class ResourceType(str, Enum):
    INSIGHT = "insight"


class ResourceStatus(str, Enum):
    COMPLETED = "completed"


class JobRepository(ABC):
    @abstractmethod
    async def update_job_status(
        self, job_id: UUID, status: JobStatus
    ) -> None: ...

    @abstractmethod
    async def create_insight_resource(
        self,
        job_id: UUID,
        user_id: str,
        thread_id: Optional[str],
        charts: list[dict],
    ) -> None: ...


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

        result = await self._service.analyze(
            aois=aois,
            dataset_id=dataset_id,
            start_date=start_date,
            end_date=end_date,
        )

        if not result.data.success:
            await self._repo.update_job_status(job_id, JobStatus.FAILED)
            return

        await self._repo.create_insight_resource(
            job_id=job_id,
            user_id=user_id,
            thread_id=thread_id,
            charts=result.charts or [],
        )
        await self._repo.update_job_status(job_id, JobStatus.COMPLETED)
