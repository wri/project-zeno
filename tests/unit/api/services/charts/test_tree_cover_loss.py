from src.api.services.charts import column_to_rows
from src.api.services.charts.tree_cover_loss import TCLChartGenerator
from tests.unit.api.services.charts.conftest import load_fixture_rows

TCL_DATA = {
    "tree_cover_loss_year": [2022, 2021, 2020],
    "area_ha": [3000.0, 0.0, 1000.0],
    "carbon_emissions_MgCO2e": [1500.0, 0.0, 500.0],
    "aoi_id": ["BRA"] * 3,
    "aoi_type": ["admin"] * 3,
}
TCL_ROWS = column_to_rows(TCL_DATA)


def test_generates_two_charts():
    charts = TCLChartGenerator().generate(TCL_ROWS)
    assert len(charts) == 2


def test_loss_chart_is_bar_with_correct_axes():
    chart = TCLChartGenerator().generate(TCL_ROWS)[0]
    fe = chart.to_frontend_dict()
    assert fe["type"] == "bar"
    assert fe["xAxis"] == "tree_cover_loss_year"
    assert fe["yAxis"] == "area_ha"
    # snake_case persistence parity
    assert chart.to_orm_kwargs()["chart_type"] == "bar"
    assert chart.to_orm_kwargs()["y_axis"] == "area_ha"


def test_emissions_chart_is_separate_bar_with_correct_axes():
    chart = TCLChartGenerator().generate(TCL_ROWS)[1]
    fe = chart.to_frontend_dict()
    assert fe["type"] == "bar"
    assert fe["xAxis"] == "tree_cover_loss_year"
    assert fe["yAxis"] == "carbon_emissions_MgCO2e"


def test_drops_rows_where_area_ha_is_zero():
    charts = TCLChartGenerator().generate(TCL_ROWS)
    for chart in charts:
        for row in chart.chart_data:
            assert row["area_ha"] != 0


def test_rows_sorted_by_year():
    # The analytics API returns rows in arbitrary order.
    chart = TCLChartGenerator().generate(TCL_ROWS)[0]
    years = [row["tree_cover_loss_year"] for row in chart.chart_data]
    assert years == [2020, 2022]


def test_real_response_shape_produces_sorted_years():
    rows = load_fixture_rows("tree_cover_loss")
    chart = TCLChartGenerator().generate(rows)[0]
    years = [row["tree_cover_loss_year"] for row in chart.chart_data]
    assert years == sorted(years)
    assert len(years) > 0
