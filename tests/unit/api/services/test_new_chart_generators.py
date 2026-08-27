"""Tests for the chart generators added for the previously-uncovered datasets.

Row shapes are taken from live analytics responses, not the catalog prose —
the two diverge (see the land cover composition vs change endpoints).
"""

import pytest

from src.agent.datasets.handlers.analytics_handler import (
    FOREST_CARBON_FLUX_ID,
    GRASSLANDS_ID,
    NATURAL_LANDS_ID,
    SLUC_EMISSION_FACTORS_ID,
    TREE_COVER_GAIN_ID,
    TREE_COVER_ID,
    TREE_COVER_LOSS_BY_DRIVER_ID,
    TREE_COVER_LOSS_BY_FIRES_ID,
)
from src.api.services.charts import (
    DETERMINISTIC_GENERATORS,
    ForestFluxChartGenerator,
    GrasslandsChartGenerator,
    NaturalLandsChartGenerator,
    SlucEmissionFactorsChartGenerator,
    TCLByDriverChartGenerator,
    TCLByFiresChartGenerator,
    TreeCoverChartGenerator,
    TreeCoverGainChartGenerator,
)

CASES = [
    (NaturalLandsChartGenerator, NATURAL_LANDS_ID),
    (GrasslandsChartGenerator, GRASSLANDS_ID),
    (TreeCoverGainChartGenerator, TREE_COVER_GAIN_ID),
    (ForestFluxChartGenerator, FOREST_CARBON_FLUX_ID),
    (TreeCoverChartGenerator, TREE_COVER_ID),
    (TCLByDriverChartGenerator, TREE_COVER_LOSS_BY_DRIVER_ID),
    (SlucEmissionFactorsChartGenerator, SLUC_EMISSION_FACTORS_ID),
    (TCLByFiresChartGenerator, TREE_COVER_LOSS_BY_FIRES_ID),
]


@pytest.mark.parametrize(("generator", "dataset_id"), CASES)
def test_handles_only_its_own_dataset(generator, dataset_id):
    assert generator(dataset_id).can_handle(dataset_id)
    assert not generator(dataset_id).can_handle(dataset_id + 1000)


@pytest.mark.parametrize(("generator", "dataset_id"), CASES)
def test_registered(generator, dataset_id):
    assert any(isinstance(g, generator) for g in DETERMINISTIC_GENERATORS)


@pytest.mark.parametrize(("generator", "dataset_id"), CASES)
def test_no_rows_means_no_charts(generator, dataset_id):
    assert generator(dataset_id).generate([]) == []


def test_natural_lands_pie_drops_zero_and_sorts_by_area():
    rows = [
        {"natural_lands_class": "Natural short vegetation", "area_ha": 84.6},
        {"natural_lands_class": "Natural forests", "area_ha": 215446.4},
        {"natural_lands_class": "Cropland", "area_ha": 0.0},
    ]
    chart = NaturalLandsChartGenerator(NATURAL_LANDS_ID).generate(rows)[0]

    assert chart.chart_type == "pie"
    assert [r["natural_lands_class"] for r in chart.chart_data] == [
        "Natural forests",
        "Natural short vegetation",
    ]


def test_grasslands_is_a_year_series_sorted_ascending():
    rows = [
        {"year": 2017, "area_ha": 4.0},
        {"year": 2015, "area_ha": 2.8},
        {"year": 2016, "area_ha": 0.0},
    ]
    chart = GrasslandsChartGenerator(GRASSLANDS_ID).generate(rows)[0]

    assert (chart.chart_type, chart.x_axis) == ("bar", "year")
    assert [r["year"] for r in chart.chart_data] == [2015, 2017]


def test_tree_cover_gain_keeps_raw_cumulative_period_labels():
    """The periods overlap, so they must not be decomposed or renamed."""
    rows = [
        {"tree_cover_gain_period": "2015-2020", "area_ha": 265.4},
        {"tree_cover_gain_period": "2000-2020", "area_ha": 900.1},
    ]
    chart = TreeCoverGainChartGenerator(TREE_COVER_GAIN_ID).generate(rows)[0]

    assert chart.x_axis == "tree_cover_gain_period"
    assert [r["tree_cover_gain_period"] for r in chart.chart_data] == [
        "2000-2020",
        "2015-2020",
    ]


def test_forest_flux_negates_removals_so_the_bar_diverges():
    rows = [
        {
            "carbon_gross_emissions_Mg_CO2e": 9837012.2,
            "carbon_gross_removals_Mg_CO2e": 17261177.1,
            "carbon_net_flux_Mg_CO2e": -7424164.9,
        }
    ]
    chart = ForestFluxChartGenerator(FOREST_CARBON_FLUX_ID).generate(rows)[0]

    values = {r["flux"]: r["carbon_MgCO2e"] for r in chart.chart_data}
    assert values["Gross emissions"] > 0
    assert values["Gross removals"] < 0
    assert values["Net flux"] == pytest.approx(-7424164.9)


def test_tcl_by_driver_excludes_unknown():
    rows = [
        {"tree_cover_loss_driver": "Permanent agriculture", "area_ha": 657.4},
        {"tree_cover_loss_driver": "Unknown", "area_ha": 31.7},
    ]
    chart = TCLByDriverChartGenerator(TREE_COVER_LOSS_BY_DRIVER_ID).generate(
        rows
    )[0]

    assert [r["tree_cover_loss_driver"] for r in chart.chart_data] == [
        "Permanent agriculture"
    ]


def test_sluc_totals_emissions_by_gas_and_crop():
    rows = [
        {"crop_type": "Banana", "gas_type": "CH4", "emissions_tCO2e": 11.9},
        {"crop_type": "Banana", "gas_type": "CH4", "emissions_tCO2e": 11.4},
        {"crop_type": "Cocoa", "gas_type": "CO2", "emissions_tCO2e": 50.0},
    ]
    pie, table = SlucEmissionFactorsChartGenerator(
        SLUC_EMISSION_FACTORS_ID
    ).generate(rows)

    assert pie.chart_type == "pie"
    assert {r["gas_type"]: r["emissions_tCO2e"] for r in pie.chart_data} == {
        "CO2": 50.0,
        "CH4": pytest.approx(23.3),
    }
    assert table.chart_type == "table"
    assert [r["crop_type"] for r in table.chart_data] == ["Cocoa", "Banana"]


def test_fires_stacks_by_year_when_several_years_present():
    rows = [
        {
            "tree_cover_loss_year": 2020,
            "tree_cover_loss_from_fires_area_ha": 20.6,
            "tree_cover_loss_non_fires_area_ha": 909.5,
        },
        {
            "tree_cover_loss_year": 2017,
            "tree_cover_loss_from_fires_area_ha": 96.8,
            "tree_cover_loss_non_fires_area_ha": 856.9,
        },
    ]
    chart = TCLByFiresChartGenerator(TREE_COVER_LOSS_BY_FIRES_ID).generate(
        rows
    )[0]

    assert chart.chart_type == "stacked-bar"
    assert chart.series_fields == [
        "tree_cover_loss_from_fires_area_ha",
        "tree_cover_loss_non_fires_area_ha",
    ]
    assert [r["tree_cover_loss_year"] for r in chart.chart_data] == [
        2017,
        2020,
    ]


def test_fires_falls_back_to_a_pie_for_a_single_year():
    rows = [
        {
            "tree_cover_loss_year": 2020,
            "tree_cover_loss_from_fires_area_ha": 20.6,
            "tree_cover_loss_non_fires_area_ha": 909.5,
        }
    ]
    chart = TCLByFiresChartGenerator(TREE_COVER_LOSS_BY_FIRES_ID).generate(
        rows
    )[0]

    assert chart.chart_type == "pie"
    assert [r["cause"] for r in chart.chart_data] == ["Fires", "Other"]


def test_sluc_pie_excludes_the_co2e_total():
    """CO2e is the sum of the individual gases, not a fourth gas — leaving it
    in makes it exactly half the pie."""
    rows = [
        {"crop_type": "Banana", "gas_type": "CO2", "emissions_tCO2e": 100.0},
        {"crop_type": "Banana", "gas_type": "CH4", "emissions_tCO2e": 10.0},
        {"crop_type": "Banana", "gas_type": "N2O", "emissions_tCO2e": 5.0},
        {"crop_type": "Banana", "gas_type": "CO2e", "emissions_tCO2e": 115.0},
    ]
    pie, table = SlucEmissionFactorsChartGenerator(
        SLUC_EMISSION_FACTORS_ID
    ).generate(rows)

    assert [r["gas_type"] for r in pie.chart_data] == ["CO2", "CH4", "N2O"]
    assert table.chart_data == [
        {"crop_type": "Banana", "emissions_tCO2e": 115.0}
    ]
