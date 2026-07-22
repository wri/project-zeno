from src.api.services.charts import column_to_rows
from src.api.services.charts.tree_cover_gain import (
    TreeCoverGainChartGenerator,
)
from tests.unit.api.services.charts.conftest import load_fixture_rows

ROWS = column_to_rows(
    {
        "tree_cover_gain_period": ["2010-2015", "2000-2005", "2005-2010"],
        "area_ha": [30.0, 10.0, 0.0],
        "aoi_id": ["CRI"] * 3,
        "aoi_type": ["admin"] * 3,
    }
)


def test_single_bar_chart_of_area_by_period():
    charts = TreeCoverGainChartGenerator().generate(ROWS)
    assert len(charts) == 1
    fe = charts[0].to_frontend_dict()
    assert fe["type"] == "bar"
    assert fe["xAxis"] == "tree_cover_gain_period"
    assert fe["yAxis"] == "area_ha"
    assert "(ha)" in fe["title"]


def test_periods_sorted_and_zero_area_dropped():
    chart = TreeCoverGainChartGenerator().generate(ROWS)[0]
    periods = [row["tree_cover_gain_period"] for row in chart.chart_data]
    assert periods == ["2000-2005", "2010-2015"]


def test_real_response_shape_covers_all_periods():
    rows = load_fixture_rows("tree_cover_gain")
    chart = TreeCoverGainChartGenerator().generate(rows)[0]
    periods = [row["tree_cover_gain_period"] for row in chart.chart_data]
    assert periods == [
        "2000-2005",
        "2005-2010",
        "2010-2015",
        "2015-2020",
    ]
