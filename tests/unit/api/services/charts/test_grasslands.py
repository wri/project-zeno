from src.api.services.charts import column_to_rows
from src.api.services.charts.grasslands import GrasslandsChartGenerator
from tests.unit.api.services.charts.conftest import load_fixture_rows

ROWS = column_to_rows(
    {
        "year": [2002, 2000, 2001],
        "area_ha": [110.0, 100.0, 0.0],
        "aoi_id": ["KEN"] * 3,
        "aoi_type": ["admin"] * 3,
    }
)


def test_single_line_chart_of_area_by_year():
    charts = GrasslandsChartGenerator().generate(ROWS)
    assert len(charts) == 1
    fe = charts[0].to_frontend_dict()
    assert fe["type"] == "line"
    assert fe["xAxis"] == "year"
    assert fe["yAxis"] == "area_ha"
    assert "(ha)" in fe["title"]


def test_rows_sorted_by_year_and_zero_area_dropped():
    chart = GrasslandsChartGenerator().generate(ROWS)[0]
    years = [row["year"] for row in chart.chart_data]
    assert years == [2000, 2002]  # 2001 dropped (area 0), rest sorted


def test_real_response_shape_produces_full_series():
    rows = load_fixture_rows("grasslands")
    chart = GrasslandsChartGenerator().generate(rows)[0]
    years = [row["year"] for row in chart.chart_data]
    assert years == sorted(years)
    assert len(years) == 23  # Kenya 2000-2022
    assert all(row["area_ha"] > 0 for row in chart.chart_data)
