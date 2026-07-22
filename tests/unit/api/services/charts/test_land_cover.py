from src.api.services.charts import column_to_rows
from src.api.services.charts.land_cover import LandCoverChartGenerator
from tests.unit.api.services.charts.conftest import load_fixture_rows

ROWS = column_to_rows(
    {
        "land_cover_class": ["Tree cover", "Cropland", "Water"],
        "area_ha": [300.0, 100.0, 0.0],
        "aoi_id": ["CRI"] * 3,
        "aoi_type": ["admin"] * 3,
    }
)


def test_single_composition_pie():
    charts = LandCoverChartGenerator().generate(ROWS)
    assert len(charts) == 1
    fe = charts[0].to_frontend_dict()
    assert fe["type"] == "pie"
    assert fe["xAxis"] == "land_cover_class"
    assert fe["yAxis"] == "area_ha"
    assert "2024" in fe["title"] and "(ha)" in fe["title"]


def test_zero_area_classes_dropped_and_sorted_descending():
    chart = LandCoverChartGenerator().generate(ROWS)[0]
    assert [row["land_cover_class"] for row in chart.chart_data] == [
        "Tree cover",
        "Cropland",
    ]


def test_real_response_shape_produces_class_slices():
    rows = load_fixture_rows("land_cover_composition")
    chart = LandCoverChartGenerator().generate(rows)[0]
    classes = [row["land_cover_class"] for row in chart.chart_data]
    assert "Tree cover" in classes
    areas = [row["area_ha"] for row in chart.chart_data]
    assert areas == sorted(areas, reverse=True)
