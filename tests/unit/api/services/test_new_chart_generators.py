"""Tests for the chart generators added for the previously-uncovered datasets.

Row shapes are taken from live analytics responses, not the catalog prose —
the two diverge (see the land cover composition vs change endpoints).
"""

import re

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
    assert generator().can_handle(dataset_id)
    assert not generator().can_handle(dataset_id + 1000)


@pytest.mark.parametrize(("generator", "dataset_id"), CASES)
def test_registered(generator, dataset_id):
    assert any(isinstance(g, generator) for g in DETERMINISTIC_GENERATORS)


@pytest.mark.parametrize(("generator", "dataset_id"), CASES)
def test_no_rows_means_no_charts(generator, dataset_id):
    assert generator().generate([]) == []


def test_natural_lands_pie_drops_zero_and_sorts_by_area():
    rows = [
        {"natural_lands_class": "Natural short vegetation", "area_ha": 84.6},
        {"natural_lands_class": "Natural forests", "area_ha": 215446.4},
        {"natural_lands_class": "Cropland", "area_ha": 0.0},
    ]
    chart = NaturalLandsChartGenerator().generate(rows)[0]

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
    chart = GrasslandsChartGenerator().generate(rows)[0]

    assert (chart.chart_type, chart.x_axis) == ("bar", "year")
    assert [r["year"] for r in chart.chart_data] == [2015, 2017]


def test_tree_cover_gain_keeps_raw_cumulative_period_labels():
    """The periods overlap, so they must not be decomposed or renamed."""
    rows = [
        {"tree_cover_gain_period": "2015-2020", "area_ha": 265.4},
        {"tree_cover_gain_period": "2000-2020", "area_ha": 900.1},
    ]
    chart = TreeCoverGainChartGenerator().generate(rows)[0]

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
    chart = ForestFluxChartGenerator().generate(rows)[0]

    values = {r["flux"]: r["carbon_MgCO2e"] for r in chart.chart_data}
    assert values["charts.label.gross_emissions"] > 0
    assert values["charts.label.gross_removals"] < 0
    assert values["charts.label.net_flux"] == pytest.approx(-7424164.9)


def test_tcl_by_driver_excludes_unknown():
    rows = [
        {"tree_cover_loss_driver": "Permanent agriculture", "area_ha": 657.4},
        {"tree_cover_loss_driver": "Unknown", "area_ha": 31.7},
    ]
    chart = TCLByDriverChartGenerator().generate(rows)[0]

    assert [r["tree_cover_loss_driver"] for r in chart.chart_data] == [
        "Permanent agriculture"
    ]


def test_sluc_totals_emissions_by_gas_and_crop():
    rows = [
        {"crop_type": "Banana", "gas_type": "CH4", "emissions_tCO2e": 11.9},
        {"crop_type": "Banana", "gas_type": "CH4", "emissions_tCO2e": 11.4},
        {"crop_type": "Cocoa", "gas_type": "CO2", "emissions_tCO2e": 50.0},
    ]
    pie, table = SlucEmissionFactorsChartGenerator().generate(rows)

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
    chart = TCLByFiresChartGenerator().generate(rows)[0]

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
    chart = TCLByFiresChartGenerator().generate(rows)[0]

    assert chart.chart_type == "pie"
    assert [r["cause"] for r in chart.chart_data] == [
        "charts.label.fires",
        "charts.label.other",
    ]


def test_sluc_pie_excludes_the_co2e_total():
    """CO2e is the sum of the individual gases, not a fourth gas — leaving it
    in makes it exactly half the pie."""
    rows = [
        {"crop_type": "Banana", "gas_type": "CO2", "emissions_tCO2e": 100.0},
        {"crop_type": "Banana", "gas_type": "CH4", "emissions_tCO2e": 10.0},
        {"crop_type": "Banana", "gas_type": "N2O", "emissions_tCO2e": 5.0},
        {"crop_type": "Banana", "gas_type": "CO2e", "emissions_tCO2e": 115.0},
    ]
    pie, table = SlucEmissionFactorsChartGenerator().generate(rows)

    assert [r["gas_type"] for r in pie.chart_data] == ["CO2", "CH4", "N2O"]
    assert table.chart_data == [
        {"crop_type": "Banana", "emissions_tCO2e": 115.0}
    ]


def test_fires_pie_tolerates_a_row_missing_one_series():
    """A row qualifies if either series is positive, so the other may be
    absent — indexing it directly fails the whole analysis job."""
    chart = TCLByFiresChartGenerator().generate(
        [
            {
                "tree_cover_loss_year": 2020,
                "tree_cover_loss_from_fires_area_ha": 5.0,
            }
        ]
    )[0]

    assert {r["cause"]: r["area_ha"] for r in chart.chart_data} == {
        "charts.label.fires": 5.0,
        "charts.label.other": 0,
    }


@pytest.mark.parametrize(
    "row",
    [
        {"gas_type": "CO2", "emissions_tCO2e": 5.0},  # no crop_type
        {"crop_type": "Banana", "emissions_tCO2e": 5.0},  # no gas_type
    ],
)
def test_sluc_skips_rows_missing_a_grouping_key(row):
    assert SlucEmissionFactorsChartGenerator().generate([row]) == []


def test_forest_flux_totals_every_area_of_interest():
    """Multi-AOI requests are first class; charting only the first row
    presents one area's numbers as the answer for all of them."""
    charts = ForestFluxChartGenerator().generate(
        [
            {
                "carbon_gross_emissions_Mg_CO2e": 10.0,
                "carbon_gross_removals_Mg_CO2e": 5.0,
                "carbon_net_flux_Mg_CO2e": 5.0,
            },
            {
                "carbon_gross_emissions_Mg_CO2e": 99.0,
                "carbon_gross_removals_Mg_CO2e": 1.0,
                "carbon_net_flux_Mg_CO2e": 98.0,
            },
        ]
    )

    values = {r["flux"]: r["carbon_MgCO2e"] for r in charts[0].chart_data}
    assert values == {
        "charts.label.gross_emissions": 109.0,
        "charts.label.gross_removals": -6.0,
        "charts.label.net_flux": 103.0,
    }


@pytest.mark.parametrize(
    ("generator", "dataset_id", "rows"),
    [
        (
            NaturalLandsChartGenerator,
            NATURAL_LANDS_ID,
            [{"natural_lands_class": "Natural forests", "area_ha": 1.0}],
        ),
        (
            TreeCoverChartGenerator,
            TREE_COVER_ID,
            [{"name": "A", "area_ha": 1.0}],
        ),
        (
            TCLByDriverChartGenerator,
            TREE_COVER_LOSS_BY_DRIVER_ID,
            [{"tree_cover_loss_driver": "Logging", "area_ha": 1.0}],
        ),
        (
            ForestFluxChartGenerator,
            FOREST_CARBON_FLUX_ID,
            [{"carbon_net_flux_Mg_CO2e": 1.0}],
        ),
    ],
)
def test_titles_do_not_assert_a_period(generator, dataset_id, rows):
    """The analysis window is caller-supplied and unclamped here, so a title
    naming a fixed period can contradict the data it labels."""
    for chart in generator().generate(rows):
        assert not re.search(r"\d{4}", chart.title), chart.title
