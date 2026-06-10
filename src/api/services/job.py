from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
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


class ResourceStatus(str, Enum):
    COMPLETED = "completed"


@dataclass
class JobResourceData:
    id: UUID
    resource_url: str
    status: ResourceStatus
    created_at: datetime


@dataclass
class JobData:
    id: UUID
    user_id: str
    type: JobType
    status: JobStatus
    thread_id: Optional[str]
    resources: list[JobResourceData]
    created_at: datetime


class JobRepository(ABC):
    @abstractmethod
    async def create_job(
        self,
        user_id: str,
        thread_id: Optional[str],
        type: JobType,
    ) -> UUID: ...

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

    @abstractmethod
    async def get_job(self, job_id: UUID) -> Optional[JobData]: ...
