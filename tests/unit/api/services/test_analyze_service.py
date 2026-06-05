import pytest

from src.agent.datasets.handlers.analytics_handler import TREE_COVER_LOSS_ID
from src.agent.datasets.handlers.base import DataPullResult, DataSourceHandler
from src.api.services.analyze import AnalyzeService

LAND_COVER_CHANGE_ID = 1  # non-TCL dataset for "not implemented" tests


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
TCL_RESULT = DataPullResult(
    success=True,
    message="ok",
    data_points_count=3,
    analytics_api_url="https://analytics.example.com/result/abc123",
    data={
        "year": [2020, 2021, 2022],
        "area_ha": [1000.0, 0.0, 3000.0],
        "emissions_MgCO2e": [500.0, 0.0, 1500.0],
        "aoi_id": ["BRA"] * 3,
        "aoi_type": ["admin"] * 3,
    },
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
async def test_get_charts_returns_none_for_unimplemented_dataset():
    handler = FakeHandler(SUCCESS_RESULT)
    service = AnalyzeService(handler)

    result = await service.analyze(
        aois=[AOI],
        dataset_id=LAND_COVER_CHANGE_ID,
        start_date="2020-01-01",
        end_date="2020-12-31",
    )

    assert result.charts is None


@pytest.mark.asyncio
async def test_tcl_returns_two_charts():
    handler = FakeHandler(TCL_RESULT)
    service = AnalyzeService(handler)

    result = await service.analyze(
        aois=[AOI],
        dataset_id=TREE_COVER_LOSS_ID,
        start_date="2020-01-01",
        end_date="2022-12-31",
    )

    assert result.charts is not None
    assert len(result.charts) == 2


@pytest.mark.asyncio
async def test_tcl_loss_chart_is_bar_with_correct_axes():
    handler = FakeHandler(TCL_RESULT)
    service = AnalyzeService(handler)

    result = await service.analyze(
        aois=[AOI],
        dataset_id=TREE_COVER_LOSS_ID,
        start_date="2020-01-01",
        end_date="2022-12-31",
    )

    loss_chart = result.charts[0]
    assert loss_chart["type"] == "bar"
    assert loss_chart["xAxis"] == "year"
    assert loss_chart["yAxis"] == "area_ha"


@pytest.mark.asyncio
async def test_tcl_emissions_chart_is_separate_bar_with_correct_axes():
    handler = FakeHandler(TCL_RESULT)
    service = AnalyzeService(handler)

    result = await service.analyze(
        aois=[AOI],
        dataset_id=TREE_COVER_LOSS_ID,
        start_date="2020-01-01",
        end_date="2022-12-31",
    )

    emissions_chart = result.charts[1]
    assert emissions_chart["type"] == "bar"
    assert emissions_chart["xAxis"] == "year"
    assert emissions_chart["yAxis"] == "emissions_MgCO2e"


@pytest.mark.asyncio
async def test_tcl_charts_have_empty_insight():
    handler = FakeHandler(TCL_RESULT)
    service = AnalyzeService(handler)

    result = await service.analyze(
        aois=[AOI],
        dataset_id=TREE_COVER_LOSS_ID,
        start_date="2020-01-01",
        end_date="2022-12-31",
    )

    for chart in result.charts:
        assert chart["insight"] == ""


@pytest.mark.asyncio
async def test_tcl_charts_have_no_generation_field():
    handler = FakeHandler(TCL_RESULT)
    service = AnalyzeService(handler)

    result = await service.analyze(
        aois=[AOI],
        dataset_id=TREE_COVER_LOSS_ID,
        start_date="2020-01-01",
        end_date="2022-12-31",
    )

    for chart in result.charts:
        assert "generation" not in chart


@pytest.mark.asyncio
async def test_analyze_result_exposes_source_urls():
    handler = FakeHandler(TCL_RESULT)
    service = AnalyzeService(handler)

    result = await service.analyze(
        aois=[AOI],
        dataset_id=TREE_COVER_LOSS_ID,
        start_date="2020-01-01",
        end_date="2022-12-31",
    )

    assert result.source_urls == [TCL_RESULT.analytics_api_url]


@pytest.mark.asyncio
async def test_tcl_drops_rows_where_area_ha_is_zero():
    handler = FakeHandler(TCL_RESULT)
    service = AnalyzeService(handler)

    result = await service.analyze(
        aois=[AOI],
        dataset_id=TREE_COVER_LOSS_ID,
        start_date="2020-01-01",
        end_date="2022-12-31",
    )

    for chart in result.charts:
        for row in chart["data"]:
            assert row["area_ha"] != 0
