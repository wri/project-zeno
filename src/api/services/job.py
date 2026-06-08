from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional
from uuid import UUID


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
