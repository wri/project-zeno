from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.agent.subagents.analyst.charts import Insight
from src.api.data_models import (
    JobOrm,
    JobResourceOrm,
)
from src.api.repositories.insight_writer import persist_insight
from src.api.services.job import (
    JobData,
    JobRepository,
    JobResourceData,
    JobStatus,
    JobType,
    ResourceStatus,
)
from src.shared.database import get_session_from_pool
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class DBJobRepository(JobRepository):
    async def create_job(
        self, user_id: str, thread_id: Optional[str], type: JobType
    ) -> UUID:
        async with get_session_from_pool() as session:
            row = JobOrm(
                user_id=user_id,
                thread_id=thread_id,
                type=type.value,
                status=JobStatus.PENDING.value,
            )
            session.add(row)
            await session.flush()
            job_id = row.id
            await session.commit()
            return job_id

    async def update_job_status(self, job_id: UUID, status: JobStatus) -> None:
        async with get_session_from_pool() as session:
            row = await session.get(JobOrm, job_id)
            if row:
                row.status = status.value
                await session.commit()

    async def create_insight_resource(
        self,
        job_id: UUID,
        user_id: str,
        thread_id: Optional[str],
        insight: Insight,
    ) -> str:
        insight_id = await persist_insight(
            insight,
            user_id=user_id,
            thread_id=thread_id or "",
        )
        async with get_session_from_pool() as session:
            session.add(
                JobResourceOrm(
                    job_id=job_id,
                    resource_url=f"/api/insights/{insight_id}",
                    status=ResourceStatus.COMPLETED.value,
                )
            )
            await session.commit()
        logger.info(
            "insight_resource_created",
            job_id=str(job_id),
            insight_id=insight_id,
            charts_count=len(insight.charts),
        )
        return insight_id

    async def get_job(self, job_id: UUID) -> Optional[JobData]:
        async with get_session_from_pool() as session:
            result = await session.execute(
                select(JobOrm)
                .options(selectinload(JobOrm.resources))
                .where(JobOrm.id == job_id)
            )
            row = result.scalars().first()
            if not row:
                return None
            return JobData(
                id=row.id,
                user_id=row.user_id,
                type=JobType(row.type),
                status=JobStatus(row.status),
                thread_id=row.thread_id,
                created_at=row.created_at,
                resources=[
                    JobResourceData(
                        id=r.id,
                        resource_url=r.resource_url,
                        status=ResourceStatus(r.status),
                        created_at=r.created_at,
                    )
                    for r in row.resources
                ],
            )


def get_job_repository() -> JobRepository:
    return DBJobRepository()
