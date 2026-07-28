"""DB-backed tests for the single-transaction job persistence methods.

The point of `create_completed_job` is atomicity: the job, the insight, its
charts and the resource row either all exist or none do — a crash or error
mid-cycle must not leave orphaned insights or jobs stuck in a non-terminal
status.
"""

from unittest.mock import patch

import pytest
from sqlalchemy import func, select

from src.agent.subagents.analyst.charts import Insight, InsightChart
from src.api.data_models import (
    InsightChartOrm,
    InsightOrm,
    JobOrm,
    JobResourceOrm,
    UserOrm,
)
from src.api.repositories.job_repository import DBJobRepository
from src.api.services.job import JobStatus, JobType, ResourceStatus
from tests.conftest import async_session_maker

USER_ID = "user-job-repo"

INSIGHT = Insight(
    charts=[
        InsightChart(
            position=0,
            title="Annual Tree Cover Loss",
            chart_type="bar",
            x_axis="tree_cover_loss_year",
            y_axis="area_ha",
            chart_data=[{"tree_cover_loss_year": 2020, "area_ha": 1000.0}],
        ),
        InsightChart(
            position=1,
            title="Loss by Region",
            chart_type="pie",
            x_axis="region",
            y_axis="area_ha",
            chart_data=[{"region": "Norte", "area_ha": 600.0}],
        ),
    ]
)


async def _create_user() -> None:
    async with async_session_maker() as session:
        session.add(
            UserOrm(id=USER_ID, name=USER_ID, email=f"{USER_ID}@example.com")
        )
        await session.commit()


async def _count(orm_cls) -> int:
    async with async_session_maker() as session:
        result = await session.execute(
            select(func.count()).select_from(orm_cls)
        )
        return result.scalar_one()


async def test_create_completed_job_persists_full_cycle():
    await _create_user()
    repo = DBJobRepository()

    job = await repo.create_completed_job(
        user_id=USER_ID,
        thread_id="t-1",
        type=JobType.ANALYSIS,
        insight=INSIGHT,
    )

    assert job.status == JobStatus.COMPLETED
    assert job.user_id == USER_ID
    assert job.thread_id == "t-1"
    assert len(job.resources) == 1
    assert job.resources[0].status == ResourceStatus.COMPLETED
    assert job.resources[0].resource_url.startswith("/api/insights/")

    assert await _count(JobOrm) == 1
    assert await _count(InsightOrm) == 1
    assert await _count(InsightChartOrm) == 2
    assert await _count(JobResourceOrm) == 1


async def test_create_completed_job_resource_points_at_insight():
    await _create_user()
    repo = DBJobRepository()

    job = await repo.create_completed_job(
        user_id=USER_ID,
        thread_id=None,
        type=JobType.ANALYSIS,
        insight=INSIGHT,
    )

    async with async_session_maker() as session:
        insight_row = (
            (await session.execute(select(InsightOrm))).scalars().one()
        )
    assert job.resources[0].resource_url == f"/api/insights/{insight_row.id}"


async def test_create_completed_job_is_readable_via_get_job():
    await _create_user()
    repo = DBJobRepository()

    created = await repo.create_completed_job(
        user_id=USER_ID,
        thread_id="t-2",
        type=JobType.ANALYSIS,
        insight=INSIGHT,
    )

    fetched = await repo.get_job(created.id)
    assert fetched is not None
    assert fetched.status == JobStatus.COMPLETED
    assert [r.resource_url for r in fetched.resources] == [
        created.resources[0].resource_url
    ]


async def test_create_completed_job_failure_leaves_no_rows():
    """A failure mid-transaction must roll back the entire cycle."""
    await _create_user()
    repo = DBJobRepository()

    with patch(
        "src.api.repositories.job_repository.add_insight",
        side_effect=RuntimeError("boom"),
    ):
        with pytest.raises(RuntimeError):
            await repo.create_completed_job(
                user_id=USER_ID,
                thread_id=None,
                type=JobType.ANALYSIS,
                insight=INSIGHT,
            )

    assert await _count(JobOrm) == 0
    assert await _count(InsightOrm) == 0
    assert await _count(InsightChartOrm) == 0
    assert await _count(JobResourceOrm) == 0


async def test_create_failed_job_persists_terminal_failure():
    await _create_user()
    repo = DBJobRepository()

    job = await repo.create_failed_job(
        user_id=USER_ID,
        thread_id="t-3",
        type=JobType.ANALYSIS,
    )

    assert job.status == JobStatus.FAILED
    assert job.resources == []
    assert await _count(JobOrm) == 1
    assert await _count(InsightOrm) == 0
    assert await _count(JobResourceOrm) == 0
