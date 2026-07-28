import asyncio
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

import pytest

from src.agent.subagents.analyst.charts import Insight, InsightChart
from src.api.services.analysis_job import AnalysisJobRunner
from src.api.services.analyze import AnalyzeResult
from src.api.services.job import (
    JobData,
    JobRepository,
    JobResourceData,
    JobStatus,
    JobType,
    ResourceStatus,
)

USER_ID = "user123"
AOI = {"source": "gadm", "src_id": "BRA", "subtype": "country"}

CHARTS = [
    InsightChart(
        position=0,
        title="Annual Tree Cover Loss",
        chart_type="bar",
        x_axis="tree_cover_loss_year",
        y_axis="area_ha",
        chart_data=[{"tree_cover_loss_year": 2020, "area_ha": 1000.0}],
    )
]


class _Result:
    def __init__(self, success, message=""):
        self.success = success
        self.message = message


class FakeService:
    def __init__(self, *, success: bool = True, charts=CHARTS, delay: float = 0):
        self._success = success
        self._charts = charts
        self._delay = delay

    async def analyze(self, aois, dataset_id, start_date, end_date):
        if self._delay:
            await asyncio.sleep(self._delay)
        return AnalyzeResult(
            data=_Result(self._success, "upstream error"),
            charts=self._charts if self._success else [],
        )


class FakeJobRepository(JobRepository):
    def __init__(self):
        self.completed_calls: list[dict] = []
        self.failed_calls: list[dict] = []

    # --- legacy background-task methods: the sync runner must not use them ---

    async def create_job(self, user_id, thread_id, type) -> UUID:
        raise AssertionError("legacy create_job must not be called")

    async def update_job_status(self, job_id: UUID, status: JobStatus) -> None:
        raise AssertionError("legacy update_job_status must not be called")

    async def create_insight_resource(
        self,
        job_id: UUID,
        user_id: str,
        thread_id: Optional[str],
        insight: Insight,
    ) -> str:
        raise AssertionError("legacy create_insight_resource must not be called")

    # --- single-transaction methods ---

    async def create_completed_job(
        self,
        user_id: str,
        thread_id: Optional[str],
        type: JobType,
        insight: Insight,
    ) -> JobData:
        self.completed_calls.append(
            {
                "user_id": user_id,
                "thread_id": thread_id,
                "type": type,
                "insight": insight,
            }
        )
        return JobData(
            id=uuid4(),
            user_id=user_id,
            type=type,
            status=JobStatus.COMPLETED,
            thread_id=thread_id,
            created_at=datetime.now(),
            resources=[
                JobResourceData(
                    id=uuid4(),
                    resource_url="/api/insights/insight-123",
                    status=ResourceStatus.COMPLETED,
                    created_at=datetime.now(),
                )
            ],
        )

    async def create_failed_job(
        self,
        user_id: str,
        thread_id: Optional[str],
        type: JobType,
    ) -> JobData:
        self.failed_calls.append(
            {"user_id": user_id, "thread_id": thread_id, "type": type}
        )
        return JobData(
            id=uuid4(),
            user_id=user_id,
            type=type,
            status=JobStatus.FAILED,
            thread_id=thread_id,
            created_at=datetime.now(),
            resources=[],
        )

    async def get_job(self, job_id: UUID):
        return None


def make_runner(repo, service=None, **kwargs):
    return AnalysisJobRunner(service or FakeService(), repo, **kwargs)


async def _run(runner, **overrides):
    kwargs = {
        "user_id": USER_ID,
        "aois": [AOI],
        "dataset_id": 4,
        "start_date": "2020-01-01",
        "end_date": "2022-12-31",
    }
    return await runner.run(**{**kwargs, **overrides})


@pytest.mark.asyncio
async def test_run_returns_completed_job():
    repo = FakeJobRepository()
    job = await _run(make_runner(repo))

    assert job.status == JobStatus.COMPLETED
    assert len(job.resources) == 1
    assert len(repo.completed_calls) == 1
    assert repo.failed_calls == []


@pytest.mark.asyncio
async def test_run_persists_charts_only_insight():
    repo = FakeJobRepository()
    await _run(make_runner(repo))

    insight = repo.completed_calls[0]["insight"]
    assert len(insight.charts) == 1
    # The /api/analyze path persists charts only; no LLM-generated narrative.
    assert insight.primary_insight == ""
    assert insight.follow_up_suggestions == []


@pytest.mark.asyncio
async def test_run_passes_thread_id_through():
    repo = FakeJobRepository()
    await _run(make_runner(repo), thread_id="t-1")

    assert repo.completed_calls[0]["thread_id"] == "t-1"


@pytest.mark.asyncio
async def test_run_on_analytics_failure_returns_failed_job():
    repo = FakeJobRepository()
    job = await _run(make_runner(repo, FakeService(success=False)))

    assert job.status == JobStatus.FAILED
    assert job.resources == []
    assert repo.completed_calls == []
    assert len(repo.failed_calls) == 1


@pytest.mark.asyncio
async def test_run_on_service_exception_returns_failed_job():
    class BoomService:
        async def analyze(self, aois, dataset_id, start_date, end_date):
            raise RuntimeError("analytics api down")

    repo = FakeJobRepository()
    job = await _run(make_runner(repo, BoomService()))

    assert job.status == JobStatus.FAILED
    assert repo.completed_calls == []
    assert len(repo.failed_calls) == 1


@pytest.mark.asyncio
async def test_run_on_timeout_returns_failed_job():
    repo = FakeJobRepository()
    runner = make_runner(
        repo, FakeService(delay=5), timeout_seconds=0.01
    )
    job = await _run(runner)

    assert job.status == JobStatus.FAILED
    assert repo.completed_calls == []
    assert len(repo.failed_calls) == 1


@pytest.mark.asyncio
async def test_run_persistence_error_propagates():
    """A failed persist rolls back atomically and must surface as an error
    (router → 500), not be swallowed into a phantom success."""
    repo = FakeJobRepository()

    async def boom(*args, **kwargs):
        raise RuntimeError("db down")

    repo.create_completed_job = boom
    with pytest.raises(RuntimeError, match="db down"):
        await _run(make_runner(repo))
