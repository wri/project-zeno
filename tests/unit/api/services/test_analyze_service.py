import pytest

from src.agent.datasets.handlers.analytics_handler import INTEGRATED_ALERTS_ID
from src.agent.datasets.handlers.base import DataPullResult, DataSourceHandler
from src.agent.i18n import t
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.analyze import AnalyzeService
from src.api.services.charts import (
    ChartGenerator,
    IntegratedAlertsChartGenerator,
)

UNHANDLED_DATASET_ID = 1
HANDLED_DATASET_ID = 99

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


class FakeChartGenerator(ChartGenerator):
    dataset_id = HANDLED_DATASET_ID

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
    return AnalyzeService(handler, [FakeChartGenerator()])


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

    assert handler.last_call["dataset"] == {"dataset_id": HANDLED_DATASET_ID}
    assert handler.last_call["aois"] == [AOI]
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
async def test_integrated_alerts_chart_spans_the_requested_period():
    """The Analyses pane's alerts chart gives every day of the period a
    slot, so its axis spans the dates the user picked, quiet days too."""
    handler = FakeHandler(
        DataPullResult(
            success=True,
            data={
                "alert_date": ["2026-09-02"],
                "alert_confidence": ["high"],
                "area_ha": [3.0],
            },
            message="ok",
        )
    )
    service = AnalyzeService(handler, [IntegratedAlertsChartGenerator()])

    result = await service.analyze(
        aois=[AOI],
        dataset_id=INTEGRATED_ALERTS_ID,
        start_date="2026-09-01",
        end_date="2026-09-03",
    )

    (chart,) = result.charts
    assert [row["alert_date"] for row in chart.chart_data] == [
        "2026-09-01",
        "2026-09-02",
        "2026-09-03",
    ]


@pytest.mark.asyncio
async def test_integrated_alerts_chart_starts_where_the_data_does():
    """The Analyses pane asks for 2001 to 2025; the alerts begin on
    1 December 2023, so the axis does not give 22 empty years a slot."""
    handler = FakeHandler(
        DataPullResult(
            success=True,
            data={
                "alert_date": ["2024-03-02"],
                "alert_confidence": ["high"],
                "area_ha": [3.0],
            },
            message="ok",
        )
    )
    service = AnalyzeService(handler, [IntegratedAlertsChartGenerator()])

    result = await service.analyze(
        aois=[AOI],
        dataset_id=INTEGRATED_ALERTS_ID,
        start_date="2001-01-01",
        end_date="2025-12-31",
    )

    (chart,) = result.charts
    days = [row["alert_date"] for row in chart.chart_data]
    assert (days[0], days[-1], len(days)) == ("2023-12-01", "2025-12-31", 762)
    # The pull still asks for the request's period.
    assert handler.last_call["start_date"] == "2001-01-01"


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


@pytest.mark.asyncio
async def test_analyze_localises_titles_and_category_labels():
    """Generators emit message keys so they stay synchronous and pure; the
    service resolves them, since chart text is as user-facing as any other
    message the agent path already translates."""

    class KeyedGenerator(FakeChartGenerator):
        dataset_id = HANDLED_DATASET_ID
        label_fields = ("flux",)

        def generate(self, rows):
            return [
                InsightChart(
                    position=0,
                    title="charts.forest_flux.net",
                    chart_type="bar",
                    x_axis="flux",
                    y_axis="carbon_MgCO2e",
                    chart_data=[
                        {"flux": "charts.label.net_flux", "carbon_MgCO2e": 1}
                    ],
                )
            ]

    service = AnalyzeService(FakeHandler(SUCCESS_RESULT), [KeyedGenerator()])

    result = await service.analyze(
        aois=[AOI],
        dataset_id=HANDLED_DATASET_ID,
        start_date="2020-01-01",
        end_date="2020-12-31",
        language="es",
    )

    chart = result.charts[0]
    assert chart.title == await t("charts.forest_flux.net", "es")
    assert chart.chart_data[0]["flux"] == await t(
        "charts.label.net_flux", "es"
    )
    assert "charts." not in chart.title


@pytest.mark.asyncio
async def test_analyze_passes_context_layer_and_canopy_to_handler():
    handler = FakeHandler(SUCCESS_RESULT)
    service = make_service(handler)

    await service.analyze(
        aois=[AOI],
        dataset_id=HANDLED_DATASET_ID,
        start_date="2020-01-01",
        end_date="2022-12-31",
        context_layer="primary_forest",
        canopy_cover=50,
    )

    assert handler.last_call["dataset"] == {
        "dataset_id": HANDLED_DATASET_ID,
        "context_layer": "primary_forest",
        "parameters": [{"name": "canopy_cover", "values": [50]}],
    }
