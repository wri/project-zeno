import pytest

from src.agent.datasets.handlers.analytics_handler import (
    GRASSLANDS_ID,
    NATURAL_LANDS_ID,
    TREE_COVER_LOSS_ID,
)
from src.agent.datasets.handlers.base import DataPullResult, DataSourceHandler
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.analyze import AnalyzeService

# Real catalog ids: analyze clamps dates against the dataset catalog, so
# made-up ids would raise. "Unhandled" means absent from the generator map.
HANDLED_DATASET_ID = TREE_COVER_LOSS_ID
UNHANDLED_DATASET_ID = GRASSLANDS_ID

FAKE_CHARTS = [
    InsightChart(
        position=0,
        title="Fake",
        chart_type="bar",
        x_axis="year",
        y_axis="value",
        chart_data=[],
    )
]


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


class FakeChartGenerator:
    def generate(self, rows):
        return FAKE_CHARTS


AOI = {"source": "gadm", "src_id": "BRA", "subtype": "country"}
SUCCESS_RESULT = DataPullResult(
    success=True,
    data={"year": [2020], "area_ha": [5]},
    message="ok",
    data_points_count=5,
    analytics_api_url="https://analytics.example.com/result/abc123",
)
FAILURE_RESULT = DataPullResult(
    success=False, data=None, message="upstream error", data_points_count=0
)


def make_service(handler):
    return AnalyzeService(handler, {HANDLED_DATASET_ID: FakeChartGenerator()})


@pytest.mark.asyncio
async def test_analyze_passes_correct_args_to_handler():
    handler = FakeHandler(SUCCESS_RESULT)
    service = make_service(handler)

    await service.analyze(
        aois=[AOI],
        dataset_id=HANDLED_DATASET_ID,
        start_date="2020-01-01",
        end_date="2020-12-31",
    )

    assert handler.last_call["dataset"]["dataset_id"] == HANDLED_DATASET_ID
    assert handler.last_call["aois"] == [AOI]
    assert handler.last_call["start_date"] == "2020-01-01"
    assert handler.last_call["end_date"] == "2020-12-31"


@pytest.mark.asyncio
async def test_canopy_cover_pinned_to_catalog_default():
    handler = FakeHandler(SUCCESS_RESULT)
    service = make_service(handler)

    await service.analyze(
        aois=[AOI],
        dataset_id=HANDLED_DATASET_ID,
        start_date="2020-01-01",
        end_date="2020-12-31",
    )

    # Without explicit parameters the payload builder would use
    # max(catalog values) = 75% instead of the mandated 30% default.
    assert handler.last_call["dataset"]["parameters"] == [
        {"name": "canopy_cover", "values": [30]}
    ]


@pytest.mark.asyncio
async def test_dates_clamped_to_dataset_coverage():
    handler = FakeHandler(SUCCESS_RESULT)
    service = make_service(handler)

    await service.analyze(
        aois=[AOI],
        dataset_id=TREE_COVER_LOSS_ID,  # coverage 2001-2025
        start_date="1990-01-01",
        end_date="2030-12-31",
    )

    assert handler.last_call["start_date"] == "2001-01-01"
    assert handler.last_call["end_date"] == "2025-12-31"


@pytest.mark.asyncio
async def test_fixed_content_dataset_forces_its_full_range():
    handler = FakeHandler(SUCCESS_RESULT)
    service = make_service(handler)

    await service.analyze(
        aois=[AOI],
        dataset_id=NATURAL_LANDS_ID,  # fixed 2020 snapshot
        start_date="2001-01-01",
        end_date="2025-12-31",
    )

    assert handler.last_call["start_date"] == "2020-01-01"
    assert handler.last_call["end_date"] == "2020-12-31"


@pytest.mark.asyncio
async def test_analyze_always_passes_change_over_time_false():
    handler = FakeHandler(SUCCESS_RESULT)
    service = make_service(handler)

    await service.analyze(
        aois=[AOI],
        dataset_id=HANDLED_DATASET_ID,
        start_date="2020-01-01",
        end_date="2020-12-31",
    )

    assert handler.last_call["change_over_time_query"] is False


@pytest.mark.asyncio
async def test_analyze_returns_data_on_success():
    handler = FakeHandler(SUCCESS_RESULT)
    service = make_service(handler)

    result = await service.analyze(
        aois=[AOI],
        dataset_id=HANDLED_DATASET_ID,
        start_date="2020-01-01",
        end_date="2020-12-31",
    )

    assert result.data == SUCCESS_RESULT
    assert result.data.success is True


@pytest.mark.asyncio
async def test_analyze_propagates_failed_pull():
    handler = FakeHandler(FAILURE_RESULT)
    service = make_service(handler)

    result = await service.analyze(
        aois=[AOI],
        dataset_id=HANDLED_DATASET_ID,
        start_date="2020-01-01",
        end_date="2020-12-31",
    )

    assert result.data.success is False
    assert result.data.message == "upstream error"
    assert result.charts == []


@pytest.mark.asyncio
async def test_uses_deterministic_source_when_one_matches():
    handler = FakeHandler(SUCCESS_RESULT)
    service = make_service(handler)

    result = await service.analyze(
        aois=[AOI],
        dataset_id=HANDLED_DATASET_ID,
        start_date="2020-01-01",
        end_date="2020-12-31",
    )

    assert result.charts == FAKE_CHARTS


@pytest.mark.asyncio
async def test_no_charts_when_no_deterministic_source():
    handler = FakeHandler(SUCCESS_RESULT)
    service = make_service(handler)

    result = await service.analyze(
        aois=[AOI],
        dataset_id=UNHANDLED_DATASET_ID,
        start_date="2020-01-01",
        end_date="2020-12-31",
    )

    assert result.charts == []
