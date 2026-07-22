from src.api.services.charts import column_to_rows
from src.api.services.charts.natural_lands import NaturalLandsChartGenerator
from tests.unit.api.services.charts.conftest import load_fixture_rows

ROWS = column_to_rows(
    {
        "natural_lands_class": [
            "Natural forests",
            "Wetland natural forests",
            "Cropland",
            "Non-natural tree cover",
            "Wetland non-natural short vegetation",
            "Bare",
        ],
        "area_ha": [100.0, 50.0, 30.0, 20.0, 10.0, 5.0],
        "aoi_id": ["CRI"] * 6,
        "aoi_type": ["admin"] * 6,
    }
)


def test_two_slice_pie_of_natural_vs_non_natural():
    charts = NaturalLandsChartGenerator().generate(ROWS)
    assert len(charts) == 1
    fe = charts[0].to_frontend_dict()
    assert fe["type"] == "pie"
    assert fe["xAxis"] == "category"
    assert fe["yAxis"] == "area_ha"
    assert "2020" in fe["title"] and "(ha)" in fe["title"]


def test_classes_partitioned_and_summed():
    chart = NaturalLandsChartGenerator().generate(ROWS)[0]
    by_category = {row["category"]: row["area_ha"] for row in chart.chart_data}
    # Natural forests + wetland natural forests + bare
    assert by_category["Natural"] == 155.0
    # Cropland + non-natural tree cover + wetland non-natural short veg
    assert by_category["Non-natural"] == 60.0
    assert len(chart.chart_data) == 2


def test_real_response_partitions_all_18_classes():
    rows = load_fixture_rows("natural_lands")
    chart = NaturalLandsChartGenerator().generate(rows)[0]
    categories = {row["category"] for row in chart.chart_data}
    assert categories == {"Natural", "Non-natural"}
    total = sum(row["area_ha"] for row in chart.chart_data)
    assert total == sum(row["area_ha"] for row in rows)
