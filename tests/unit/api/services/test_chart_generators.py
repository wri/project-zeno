from src.agent.datasets.handlers.analytics_handler import TREE_COVER_LOSS_ID
from src.agent.datasets.handlers.base import DataPullResult
from src.api.services.charts import TCLChartGenerator

TCL_DATA = {
    "year": [2020, 2021, 2022],
    "area_ha": [1000.0, 0.0, 3000.0],
    "emissions_MgCO2e": [500.0, 0.0, 1500.0],
    "aoi_id": ["BRA"] * 3,
    "aoi_type": ["admin"] * 3,
}
TCL_RESULT = DataPullResult(
    success=True,
    message="ok",
    data_points_count=3,
    analytics_api_url="https://analytics.example.com/result/abc123",
    data=TCL_DATA,
)


def test_can_handle_tcl_dataset():
    assert TCLChartGenerator().can_handle(TREE_COVER_LOSS_ID)


def test_cannot_handle_other_dataset():
    assert not TCLChartGenerator().can_handle(1)


def test_generates_two_charts():
    charts = TCLChartGenerator().generate(TCL_RESULT)
    assert len(charts) == 2


def test_loss_chart_is_bar_with_correct_axes():
    chart = TCLChartGenerator().generate(TCL_RESULT)[0]
    assert chart["type"] == "bar"
    assert chart["xAxis"] == "year"
    assert chart["yAxis"] == "area_ha"


def test_emissions_chart_is_separate_bar_with_correct_axes():
    chart = TCLChartGenerator().generate(TCL_RESULT)[1]
    assert chart["type"] == "bar"
    assert chart["xAxis"] == "year"
    assert chart["yAxis"] == "emissions_MgCO2e"


def test_drops_rows_where_area_ha_is_zero():
    charts = TCLChartGenerator().generate(TCL_RESULT)
    for chart in charts:
        for row in chart["data"]:
            assert row["area_ha"] != 0


def test_charts_have_empty_insight():
    charts = TCLChartGenerator().generate(TCL_RESULT)
    for chart in charts:
        assert chart["insight"] == ""


def test_charts_have_no_generation_field():
    charts = TCLChartGenerator().generate(TCL_RESULT)
    for chart in charts:
        assert "generation" not in chart
