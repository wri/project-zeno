from src.api.services.charts import column_to_rows
from src.api.services.charts.carbon_flux import (
    EMISSIONS,
    NET_FLUX,
    REMOVALS,
    CarbonFluxChartGenerator,
)
from tests.unit.api.services.charts.conftest import load_fixture_rows

ROWS = column_to_rows(
    {
        "aoi_id": ["CRI"],
        "aoi_type": ["admin"],
        "carbon_net_flux_Mg_CO2e": [-100.0],
        "carbon_gross_emissions_Mg_CO2e": [150.0],
        "carbon_gross_removals_Mg_CO2e": [250.0],
        "name": ["Costa Rica"],
    }
)


def test_single_diverging_bar_chart():
    charts = CarbonFluxChartGenerator().generate(ROWS)
    assert len(charts) == 1
    fe = charts[0].to_frontend_dict()
    assert fe["type"] == "bar"
    assert fe["xAxis"] == "flux"
    assert fe["yAxis"] == "MgCO2e"
    assert "(MgCO2e)" in fe["title"]


def test_removals_negated_and_net_passed_through():
    chart = CarbonFluxChartGenerator().generate(ROWS)[0]
    by_flux = {row["flux"]: row["MgCO2e"] for row in chart.chart_data}
    assert by_flux[EMISSIONS] == 150.0
    assert by_flux[REMOVALS] == -250.0
    assert by_flux[NET_FLUX] == -100.0


def test_multi_aoi_rows_are_summed():
    rows = ROWS + ROWS
    chart = CarbonFluxChartGenerator().generate(rows)[0]
    by_flux = {row["flux"]: row["MgCO2e"] for row in chart.chart_data}
    assert by_flux[EMISSIONS] == 300.0
    assert by_flux[REMOVALS] == -500.0


def test_empty_rows_produce_no_charts():
    assert CarbonFluxChartGenerator().generate([]) == []


def test_real_response_is_a_net_sink_shape():
    rows = load_fixture_rows("carbon_flux")
    chart = CarbonFluxChartGenerator().generate(rows)[0]
    by_flux = {row["flux"]: row["MgCO2e"] for row in chart.chart_data}
    assert by_flux[EMISSIONS] > 0
    assert by_flux[REMOVALS] < 0
    # Net flux keeps the API's sign convention (negative = net sink).
    assert (
        abs(by_flux[NET_FLUX] - (by_flux[EMISSIONS] + by_flux[REMOVALS])) < 1.0
    )
