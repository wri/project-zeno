from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.api.data_models import (
    InsightChartOrm,
    InsightOrm,
    JobOrm,
    JobResourceOrm,
)
from src.api.services.job import (
    JobRepository,
    JobStatus,
    JobType,
    ResourceStatus,
)
from src.shared.database import get_session_from_pool


@dataclass
class JobResourceData:
    id: UUID
    resource_url: str
    status: ResourceStatus
    created_at: datetime


@dataclass
class JobData:
    id: UUID
    type: JobType
    status: JobStatus
    thread_id: Optional[str]
    resources: list[JobResourceData]
    created_at: datetime


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
        charts: list[dict],
    ) -> None:
        async with get_session_from_pool() as session:
            insight = InsightOrm(
                user_id=user_id,
                thread_id=thread_id or "",
                insight_text="",
                follow_up_suggestions=[],
                statistics_ids=[],
                codeact_types=[],
                codeact_contents=[],
            )
            session.add(insight)
            await session.flush()

            session.add_all(
                InsightChartOrm(
                    insight_id=insight.id,
                    position=idx,
                    title=chart.get("title", ""),
                    chart_type=chart.get("type", "bar"),
                    x_axis=chart.get("xAxis", ""),
                    y_axis=chart.get("yAxis", ""),
                    color_field=chart.get("colorField", ""),
                    stack_field=chart.get("stackField", ""),
                    group_field=chart.get("groupField", ""),
                    series_fields=chart.get("seriesFields", []),
                    chart_data=chart.get("data", []),
                )
                for idx, chart in enumerate(charts)
            )

            session.add(
                JobResourceOrm(
                    job_id=job_id,
                    resource_url=f"/api/insights/{insight.id}",
                    status=ResourceStatus.COMPLETED.value,
                )
            )
            await session.commit()

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
