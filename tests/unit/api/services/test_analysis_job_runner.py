from typing import Optional
from uuid import UUID, uuid4

import pytest

from src.agent.datasets.handlers.base import DataPullResult, DataSourceHandler
from src.api.services.analysis_job import (
    AnalysisJobRunner,
    JobRepository,
    JobStatus,
)
from src.api.services.analyze import AnalyzeService
from src.api.services.charts import ChartGenerator

JOB_ID = uuid4()
USER_ID = "user123"
AOI = {
    "source": "gadm",
    "src_id": "BRA",
    "subtype": "country",
    "name": "Brazil",
}

SUCCESS_RESULT = DataPullResult(
    success=True,
    data={
        "tree_cover_loss_year": [2020],
        "area_ha": [1000.0],
        "carbon_emissions_MgCO2e": [500.0],
        "aoi_id": ["BRA"],
        "aoi_type": ["admin"],
    },
    message="ok",
    data_points_count=1,
    analytics_api_url="https://analytics.example.com/abc",
)
FAILURE_RESULT = DataPullResult(
    success=False, data=None, message="upstream error", data_points_count=0
)


class FakeHandler(DataSourceHandler):
    def __init__(self, result: DataPullResult):
        self._result = result

    def can_handle(self, dataset) -> bool:
        return True

    async def pull_data(
        self,
        query,
        dataset,
        start_date,
        end_date,
        change_over_time_query,
        aois,
    ):
        return self._result


class FakeChartGenerator(ChartGenerator):
    def can_handle(self, dataset_id: int) -> bool:
        return True

    def generate(self, result: DataPullResult) -> list[dict]:
        return [{"id": "chart_0", "type": "bar", "title": "Test"}]


class FakeJobRepository(JobRepository):
    def __init__(self):
        self.job_statuses: list[tuple[UUID, JobStatus]] = []
        self.insight_resources: list[dict] = []

    async def update_job_status(self, job_id: UUID, status: JobStatus) -> None:
        self.job_statuses.append((job_id, status))

    async def create_insight_resource(
        self,
        job_id: UUID,
        user_id: str,
        thread_id: Optional[str],
        charts: list[dict],
    ) -> None:
        self.insight_resources.append(
            {
                "job_id": job_id,
                "user_id": user_id,
                "thread_id": thread_id,
                "charts": charts,
            }
        )


def make_service(result: DataPullResult) -> AnalyzeService:
    return AnalyzeService(FakeHandler(result), [FakeChartGenerator()])


@pytest.mark.asyncio
async def test_run_sets_job_to_running_then_completed():
    repo = FakeJobRepository()
    runner = AnalysisJobRunner(make_service(SUCCESS_RESULT), repo)

    await runner.run(JOB_ID, USER_ID, [AOI], 4, "2020-01-01", "2022-12-31")

    assert repo.job_statuses[0] == (JOB_ID, JobStatus.RUNNING)
    assert repo.job_statuses[-1] == (JOB_ID, JobStatus.COMPLETED)


@pytest.mark.asyncio
async def test_run_creates_insight_resource_on_success():
    repo = FakeJobRepository()
    runner = AnalysisJobRunner(make_service(SUCCESS_RESULT), repo)

    await runner.run(JOB_ID, USER_ID, [AOI], 4, "2020-01-01", "2022-12-31")

    assert len(repo.insight_resources) == 1
    assert repo.insight_resources[0]["job_id"] == JOB_ID
    assert repo.insight_resources[0]["user_id"] == USER_ID


@pytest.mark.asyncio
async def test_run_passes_charts_to_insight_resource():
    repo = FakeJobRepository()
    runner = AnalysisJobRunner(make_service(SUCCESS_RESULT), repo)

    await runner.run(JOB_ID, USER_ID, [AOI], 4, "2020-01-01", "2022-12-31")

    assert len(repo.insight_resources[0]["charts"]) > 0


@pytest.mark.asyncio
async def test_run_passes_thread_id_to_insight_resource():
    repo = FakeJobRepository()
    runner = AnalysisJobRunner(make_service(SUCCESS_RESULT), repo)

    await runner.run(
        JOB_ID,
        USER_ID,
        [AOI],
        4,
        "2020-01-01",
        "2022-12-31",
        thread_id="t-123",
    )

    assert repo.insight_resources[0]["thread_id"] == "t-123"


@pytest.mark.asyncio
async def test_run_on_failure_sets_job_to_failed():
    repo = FakeJobRepository()
    runner = AnalysisJobRunner(make_service(FAILURE_RESULT), repo)

    await runner.run(JOB_ID, USER_ID, [AOI], 4, "2020-01-01", "2022-12-31")

    assert repo.job_statuses[-1] == (JOB_ID, JobStatus.FAILED)


@pytest.mark.asyncio
async def test_run_on_failure_does_not_create_insight_resource():
    repo = FakeJobRepository()
    runner = AnalysisJobRunner(make_service(FAILURE_RESULT), repo)

    await runner.run(JOB_ID, USER_ID, [AOI], 4, "2020-01-01", "2022-12-31")

    assert len(repo.insight_resources) == 0
