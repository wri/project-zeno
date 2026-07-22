from src.api.services.charts import column_to_rows
from src.api.services.charts.sluc_emission_factors import (
    SlucEmissionFactorsChartGenerator,
)
from tests.unit.api.services.charts.conftest import load_fixture_rows

ROWS = column_to_rows(
    {
        "crop_type": ["Cocoa", "Cocoa", "Cocoa", "Banana", "Banana"],
        "gas_type": ["CO2e", "CO2e", "CH4", "CO2e", "N2O"],
        "year": [2020, 2021, 2020, 2020, 2020],
        "emissions_tCO2e": [10.0, 20.0, 999.0, 100.0, 999.0],
        "emissions_factor_tCO2e_per_tonne_production": [
            0.2,
            0.4,
            9.9,
            0.5,
            9.9,
        ],
        "production_tonnes": [50.0, 50.0, 50.0, 200.0, 200.0],
        "aoi_id": ["CRI"] * 5,
        "aoi_type": ["admin"] * 5,
    }
)


def test_single_table_of_crops():
    charts = SlucEmissionFactorsChartGenerator().generate(ROWS)
    assert len(charts) == 1
    fe = charts[0].to_frontend_dict()
    assert fe["type"] == "table"
    assert "tCO2e" in fe["title"]


def test_only_co2e_totals_are_tabled_and_sorted_descending():
    chart = SlucEmissionFactorsChartGenerator().generate(ROWS)[0]
    # Banana (100) before Cocoa (10 + 20); per-gas CH4/N2O rows excluded.
    assert [row["crop"] for row in chart.chart_data] == ["Banana", "Cocoa"]
    by_crop = {row["crop"]: row for row in chart.chart_data}
    assert by_crop["Cocoa"]["emissions_tCO2e"] == 30.0
    assert by_crop["Banana"]["emissions_tCO2e"] == 100.0


def test_emission_factor_is_averaged_across_years():
    chart = SlucEmissionFactorsChartGenerator().generate(ROWS)[0]
    by_crop = {row["crop"]: row for row in chart.chart_data}
    factor = by_crop["Cocoa"]["avg_emission_factor_tCO2e_per_tonne"]
    assert abs(factor - 0.3) < 1e-9  # mean of 0.2 and 0.4, not their sum


def test_real_response_shape_produces_crop_rows():
    rows = load_fixture_rows("sluc_emission_factors")
    chart = SlucEmissionFactorsChartGenerator().generate(rows)[0]
    assert len(chart.chart_data) > 5
    emissions = [row["emissions_tCO2e"] for row in chart.chart_data]
    assert emissions == sorted(emissions, reverse=True)
    assert all(
        row["avg_emission_factor_tCO2e_per_tonne"] is not None
        for row in chart.chart_data
    )
