from typing import Optional
from uuid import UUID, uuid4

import pytest

from src.agent.subagents.analyst.charts import Insight, InsightChart
from src.api.services.analysis_job import AnalysisJobRunner
from src.api.services.analyze import AnalyzeResult
from src.api.services.job import JobRepository, JobStatus

JOB_ID = uuid4()
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
    def __init__(self, *, success: bool, charts):
        self._success = success
        self._charts = charts

    async def analyze(self, aois, dataset_id, start_date, end_date):
        return AnalyzeResult(
            data=_Result(self._success, "upstream error"),
            charts=self._charts if self._success else [],
        )


class FakeJobRepository(JobRepository):
    def __init__(self):
        self.job_statuses: list[tuple[UUID, JobStatus]] = []
        self.insight_resources: list[dict] = []

    async def create_job(self, user_id, thread_id, type) -> UUID:
        return uuid4()

    async def update_job_status(self, job_id: UUID, status: JobStatus) -> None:
        self.job_statuses.append((job_id, status))

    async def create_insight_resource(
        self,
        job_id: UUID,
        user_id: str,
        thread_id: Optional[str],
        insight: Insight,
    ) -> str:
        self.insight_resources.append(
            {
                "job_id": job_id,
                "user_id": user_id,
                "thread_id": thread_id,
                "insight": insight,
            }
        )
        return "insight-123"

    async def get_job(self, job_id: UUID):
        return None


def make_runner(repo, *, success=True, charts=CHARTS):
    return AnalysisJobRunner(FakeService(success=success, charts=charts), repo)


@pytest.mark.asyncio
async def test_run_sets_job_to_running_then_completed():
    repo = FakeJobRepository()
    runner = make_runner(repo)

    await runner.run(JOB_ID, USER_ID, [AOI], 4, "2020-01-01", "2022-12-31")

    assert repo.job_statuses[0] == (JOB_ID, JobStatus.RUNNING)
    assert repo.job_statuses[-1] == (JOB_ID, JobStatus.COMPLETED)


@pytest.mark.asyncio
async def test_run_creates_insight_resource_with_charts_only():
    repo = FakeJobRepository()
    runner = make_runner(repo)

    await runner.run(JOB_ID, USER_ID, [AOI], 4, "2020-01-01", "2022-12-31")

    assert len(repo.insight_resources) == 1
    insight = repo.insight_resources[0]["insight"]
    assert len(insight.charts) == 1
    # The /api/analyze path persists charts only; no LLM-generated narrative.
    assert insight.primary_insight == ""
    assert insight.follow_up_suggestions == []


@pytest.mark.asyncio
async def test_run_passes_thread_id_to_insight_resource():
    repo = FakeJobRepository()
    runner = make_runner(repo)

    await runner.run(
        JOB_ID, USER_ID, [AOI], 4, "2020-01-01", "2022-12-31", thread_id="t-1"
    )

    assert repo.insight_resources[0]["thread_id"] == "t-1"


@pytest.mark.asyncio
async def test_run_on_failure_sets_job_to_failed():
    repo = FakeJobRepository()
    runner = make_runner(repo, success=False)

    await runner.run(JOB_ID, USER_ID, [AOI], 4, "2020-01-01", "2022-12-31")

    assert repo.job_statuses[-1] == (JOB_ID, JobStatus.FAILED)


@pytest.mark.asyncio
async def test_run_on_failure_does_not_create_insight_resource():
    repo = FakeJobRepository()
    runner = make_runner(repo, success=False)

    await runner.run(JOB_ID, USER_ID, [AOI], 4, "2020-01-01", "2022-12-31")

    assert len(repo.insight_resources) == 0


@pytest.mark.asyncio
async def test_run_marks_job_failed_when_persistence_raises():
    repo = FakeJobRepository()

    async def boom(*args, **kwargs):
        raise RuntimeError("db down")

    repo.create_insight_resource = boom
    runner = make_runner(repo)

    # Must not propagate out of the background task...
    await runner.run(JOB_ID, USER_ID, [AOI], 4, "2020-01-01", "2022-12-31")

    # ...and the job must reach a terminal FAILED state, not stay RUNNING.
    assert repo.job_statuses[-1] == (JOB_ID, JobStatus.FAILED)
