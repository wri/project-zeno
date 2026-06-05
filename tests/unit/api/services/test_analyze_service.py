import pytest

from src.agent.datasets.handlers.base import DataPullResult, DataSourceHandler
from src.api.services.analyze import AnalyzeService


class FakeHandler(DataSourceHandler):
    def __init__(self, result: DataPullResult):
        self._result = result
        self.last_call = {}

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
        self.last_call = {
            "query": query,
            "dataset": dataset,
            "start_date": start_date,
            "end_date": end_date,
            "change_over_time_query": change_over_time_query,
            "aois": aois,
        }
        return self._result


AOI = {
    "source": "gadm",
    "src_id": "BRA",
    "subtype": "country",
    "name": "Brazil",
}
SUCCESS_RESULT = DataPullResult(
    success=True, data={"rows": []}, message="ok", data_points_count=5
)
FAILURE_RESULT = DataPullResult(
    success=False, data=None, message="upstream error", data_points_count=0
)


@pytest.mark.asyncio
async def test_analyze_passes_correct_args_to_handler():
    handler = FakeHandler(SUCCESS_RESULT)
    service = AnalyzeService(handler)

    await service.analyze(
        aois=[AOI],
        dataset_id=4,
        start_date="2020-01-01",
        end_date="2020-12-31",
    )

    assert handler.last_call["dataset"] == {"dataset_id": 4}
    assert handler.last_call["aois"] == [AOI]
    assert handler.last_call["start_date"] == "2020-01-01"
    assert handler.last_call["end_date"] == "2020-12-31"


@pytest.mark.asyncio
async def test_analyze_always_passes_change_over_time_false():
    handler = FakeHandler(SUCCESS_RESULT)
    service = AnalyzeService(handler)

    await service.analyze(
        aois=[AOI],
        dataset_id=1,
        start_date="2020-01-01",
        end_date="2020-12-31",
    )

    assert handler.last_call["change_over_time_query"] is False


@pytest.mark.asyncio
async def test_analyze_returns_data_on_success():
    handler = FakeHandler(SUCCESS_RESULT)
    service = AnalyzeService(handler)

    result = await service.analyze(
        aois=[AOI],
        dataset_id=4,
        start_date="2020-01-01",
        end_date="2020-12-31",
    )

    assert result.data == SUCCESS_RESULT
    assert result.data.success is True


@pytest.mark.asyncio
async def test_analyze_propagates_failed_pull():
    handler = FakeHandler(FAILURE_RESULT)
    service = AnalyzeService(handler)

    result = await service.analyze(
        aois=[AOI],
        dataset_id=4,
        start_date="2020-01-01",
        end_date="2020-12-31",
    )

    assert result.data.success is False
    assert result.data.message == "upstream error"


@pytest.mark.asyncio
async def test_get_charts_not_implemented():
    handler = FakeHandler(SUCCESS_RESULT)
    service = AnalyzeService(handler)

    result = await service.analyze(
        aois=[AOI],
        dataset_id=4,
        start_date="2020-01-01",
        end_date="2020-12-31",
    )

    assert result.charts is None
