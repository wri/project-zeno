from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from src.agent.subagents.analyst.charts import Insight


class JobStatus(str, Enum):
    # PENDING/RUNNING are no longer written — jobs are persisted already
    # terminal — but remain readable for rows created by the old
    # background-task flow.
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
    async def create_completed_job(
        self,
        user_id: str,
        thread_id: Optional[str],
        type: JobType,
        insight: Insight,
    ) -> JobData:
        """Persist a finished job in one transaction.

        Writes the job (already `completed`), the insight, its charts and the
        resource row linking job → insight atomically: either the full cycle
        exists or nothing does. There is no intermediate `pending`/`running`
        state to strand if the process dies.
        """
        ...

    @abstractmethod
    async def create_failed_job(
        self,
        user_id: str,
        thread_id: Optional[str],
        type: JobType,
    ) -> JobData:
        """Persist a job that failed, as a terminal record with no resources."""
        ...

    @abstractmethod
    async def get_job(self, job_id: UUID) -> Optional[JobData]: ...
