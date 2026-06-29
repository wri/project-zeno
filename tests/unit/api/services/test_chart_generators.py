from src.agent.datasets.handlers.analytics_handler import (
    INTEGRATED_ALERTS_ID,
    TREE_COVER_LOSS_ID,
)
from src.api.services.charts import (
    DETERMINISTIC_GENERATORS,
    IntegratedAlertsChartGenerator,
    TCLChartGenerator,
    column_to_rows,
)

TCL_DATA = {
    "tree_cover_loss_year": [2020, 2021, 2022],
    "area_ha": [1000.0, 0.0, 3000.0],
    "carbon_emissions_MgCO2e": [500.0, 0.0, 1500.0],
    "aoi_id": ["BRA"] * 3,
    "aoi_type": ["admin"] * 3,
}
TCL_ROWS = column_to_rows(TCL_DATA)


def test_can_handle_tcl_dataset():
    assert TCLChartGenerator(TREE_COVER_LOSS_ID).can_handle(TREE_COVER_LOSS_ID)


def test_cannot_handle_other_dataset():
    assert not TCLChartGenerator(TREE_COVER_LOSS_ID).can_handle(1)


def test_tcl_generator_registered():
    assert any(
        isinstance(gen, TCLChartGenerator) for gen in DETERMINISTIC_GENERATORS
    )


def test_generates_two_charts():
    charts = TCLChartGenerator(TREE_COVER_LOSS_ID).generate(TCL_ROWS)
    assert len(charts) == 2


def test_loss_chart_is_bar_with_correct_axes():
    chart = TCLChartGenerator(TREE_COVER_LOSS_ID).generate(TCL_ROWS)[0]
    fe = chart.to_frontend_dict()
    assert fe["type"] == "bar"
    assert fe["xAxis"] == "tree_cover_loss_year"
    assert fe["yAxis"] == "area_ha"
    # snake_case persistence parity
    assert chart.to_orm_kwargs()["chart_type"] == "bar"
    assert chart.to_orm_kwargs()["y_axis"] == "area_ha"


def test_emissions_chart_is_separate_bar_with_correct_axes():
    chart = TCLChartGenerator(TREE_COVER_LOSS_ID).generate(TCL_ROWS)[1]
    fe = chart.to_frontend_dict()
    assert fe["type"] == "bar"
    assert fe["xAxis"] == "tree_cover_loss_year"
    assert fe["yAxis"] == "carbon_emissions_MgCO2e"


def test_drops_rows_where_area_ha_is_zero():
    charts = TCLChartGenerator(TREE_COVER_LOSS_ID).generate(TCL_ROWS)
    for chart in charts:
        for row in chart.chart_data:
            assert row["area_ha"] != 0


# --- Integrated Alerts -------------------------------------------------------
IA_DATA = {
    "alert_date": ["2024-03-01", "2024-03-20", "2024-04-05", "2024-04-18"],
    "alert_confidence": ["high", "low", "high", "high"],
    "area_ha": [10.0, 5.0, 20.0, 2.5],
    "aoi_id": ["BRA"] * 4,
    "aoi_type": ["admin"] * 4,
}
IA_ROWS = column_to_rows(IA_DATA)


def test_can_handle_integrated_alerts_dataset():
    gen = IntegratedAlertsChartGenerator(INTEGRATED_ALERTS_ID)
    assert gen.can_handle(INTEGRATED_ALERTS_ID)
    assert not gen.can_handle(TREE_COVER_LOSS_ID)


def test_integrated_alerts_generator_registered():
    assert any(
        isinstance(gen, IntegratedAlertsChartGenerator)
        for gen in DETERMINISTIC_GENERATORS
    )


def test_ia_generates_one_grouped_bar_by_confidence():
    chart = IntegratedAlertsChartGenerator().generate(IA_ROWS)[0]
    fe = chart.to_frontend_dict()
    assert fe["type"] == "bar"
    assert fe["xAxis"] == "month"
    assert fe["yAxis"] == "area_ha"
    assert fe["colorField"] == "alert_confidence"
    # snake_case persistence parity
    assert chart.to_orm_kwargs()["color_field"] == "alert_confidence"


def test_ia_aggregates_area_by_month_and_confidence():
    chart = IntegratedAlertsChartGenerator().generate(IA_ROWS)[0]
    by_key = {
        (r["month"], r["alert_confidence"]): r["area_ha"]
        for r in chart.chart_data
    }
    # March: high=10, low=5 (kept separate by confidence)
    assert by_key[("2024-03", "high")] == 10.0
    assert by_key[("2024-03", "low")] == 5.0
    # April: high alerts on two days summed (20 + 2.5)
    assert by_key[("2024-04", "high")] == 22.5
