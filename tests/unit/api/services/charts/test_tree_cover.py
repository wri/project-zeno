from src.api.services.charts import column_to_rows
from src.api.services.charts.tree_cover import TreeCoverChartGenerator
from tests.unit.api.services.charts.conftest import load_fixture_rows

ROWS = column_to_rows(
    {
        "aoi_id": ["CRI", "PAN"],
        "aoi_type": ["admin", "admin"],
        "area_ha": [3118338.4, 0.0],
        "name": ["Costa Rica", "Panama"],
    }
)


def test_single_bar_chart_of_extent_per_aoi():
    charts = TreeCoverChartGenerator().generate(ROWS)
    assert len(charts) == 1
    fe = charts[0].to_frontend_dict()
    assert fe["type"] == "bar"
    assert fe["xAxis"] == "name"
    assert fe["yAxis"] == "area_ha"
    assert "2000" in fe["title"] and "(ha)" in fe["title"]


def test_zero_area_aois_dropped():
    chart = TreeCoverChartGenerator().generate(ROWS)[0]
    assert [row["name"] for row in chart.chart_data] == ["Costa Rica"]


def test_real_response_shape_is_one_total_row():
    rows = load_fixture_rows("tree_cover")
    chart = TreeCoverChartGenerator().generate(rows)[0]
    assert len(chart.chart_data) == 1
    assert chart.chart_data[0]["area_ha"] > 0
