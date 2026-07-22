from src.api.services.charts import column_to_rows
from src.api.services.charts.tcl_drivers import TCLDriversChartGenerator
from tests.unit.api.services.charts.conftest import load_fixture_rows

ROWS = column_to_rows(
    {
        "tree_cover_loss_driver": [
            "Permanent agriculture",
            "Wildfire",
            "Unknown",
            "Logging",
        ],
        "area_ha": [200.0, 50.0, 30.0, 0.0],
        "carbon_emissions_MgCO2e": [900.0, 200.0, 100.0, 0.0],
        "aoi_id": ["CRI"] * 4,
        "aoi_type": ["admin"] * 4,
    }
)


def test_single_driver_pie():
    charts = TCLDriversChartGenerator().generate(ROWS)
    assert len(charts) == 1
    fe = charts[0].to_frontend_dict()
    assert fe["type"] == "pie"
    assert fe["xAxis"] == "tree_cover_loss_driver"
    assert fe["yAxis"] == "area_ha"
    assert "(ha)" in fe["title"]


def test_unknown_driver_and_zero_area_excluded():
    chart = TCLDriversChartGenerator().generate(ROWS)[0]
    drivers = [row["tree_cover_loss_driver"] for row in chart.chart_data]
    assert drivers == ["Permanent agriculture", "Wildfire"]


def test_real_response_shape_excludes_unknown():
    rows = load_fixture_rows("tcl_drivers")
    chart = TCLDriversChartGenerator().generate(rows)[0]
    drivers = {row["tree_cover_loss_driver"] for row in chart.chart_data}
    assert "Unknown" not in drivers
    assert len(drivers) >= 5
