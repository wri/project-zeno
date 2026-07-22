from src.api.services.charts import column_to_rows
from src.api.services.charts.tcl_fires import (
    FIRES_SERIES,
    OTHER_SERIES,
    TCLFiresChartGenerator,
)
from tests.unit.api.services.charts.conftest import load_fixture_rows

ROWS = column_to_rows(
    {
        "tree_cover_loss_year": [2021, 2020, 2022],
        "area_ha": [100.0, 50.0, 0.0],
        "carbon_emissions_MgCO2e": [900.0, 400.0, 0.0],
        "tree_cover_loss_from_fires_area_ha": [30.0, 10.0, 0.0],
        "tree_cover_loss_non_fires_area_ha": [70.0, 40.0, 0.0],
        "aoi_id": ["CRI"] * 3,
        "aoi_type": ["admin"] * 3,
    }
)


def test_single_stacked_bar_with_renamed_series():
    charts = TCLFiresChartGenerator().generate(ROWS)
    assert len(charts) == 1
    fe = charts[0].to_frontend_dict()
    assert fe["type"] == "stacked-bar"
    assert fe["xAxis"] == "tree_cover_loss_year"
    assert fe["seriesFields"] == [FIRES_SERIES, OTHER_SERIES]
    assert "(ha)" in fe["title"]


def test_rows_sorted_with_zero_total_dropped_and_fields_renamed():
    chart = TCLFiresChartGenerator().generate(ROWS)[0]
    assert [r["tree_cover_loss_year"] for r in chart.chart_data] == [
        2020,
        2021,
    ]
    first = chart.chart_data[0]
    assert first[FIRES_SERIES] == 10.0
    assert first[OTHER_SERIES] == 40.0


def test_emissions_never_plotted():
    chart = TCLFiresChartGenerator().generate(ROWS)[0]
    for row in chart.chart_data:
        assert "carbon_emissions_MgCO2e" not in row


def test_real_response_shape_produces_sorted_years():
    rows = load_fixture_rows("tcl_fires")
    chart = TCLFiresChartGenerator().generate(rows)[0]
    years = [row["tree_cover_loss_year"] for row in chart.chart_data]
    assert years == sorted(years)
    assert all(
        FIRES_SERIES in row and OTHER_SERIES in row for row in chart.chart_data
    )
