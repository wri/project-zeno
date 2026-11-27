"""Tests for the ranking charts of the tree cover loss generator."""

import pytest

from src.api.services.charts.base import ChartGenerator
from src.api.services.charts.ranking import RankedArea
from src.api.services.charts.tcl import LOSS_COLOR, TCLChartGenerator

AREAS = [
    RankedArea("KEN.1", "Baringo", "Kenya", "gadm"),
    RankedArea("KEN.2", "Bomet", "Kenya", "gadm"),
    RankedArea("KEN.3", "Bungoma", "Kenya", "gadm"),
]
ROWS = [
    {
        "aoi_id": "KEN.1",
        "tree_cover_loss_year": 2023,
        "area_ha": 10.0,
        "carbon_emissions_MgCO2e": 100.0,
    },
    {
        "aoi_id": "KEN.1",
        "tree_cover_loss_year": 2024,
        "area_ha": 5.0,
        "carbon_emissions_MgCO2e": 40.0,
    },
    {
        "aoi_id": "KEN.2",
        "tree_cover_loss_year": 2024,
        "area_ha": 30.0,
        "carbon_emissions_MgCO2e": 10.0,
    },
]


def _rank(rows):
    return TCLChartGenerator().for_areas(AREAS).generate(rows)


class _Plain(ChartGenerator):
    dataset_id = 0

    def generate(self, rows):
        return []


def test_the_default_generator_ignores_the_areas():
    generator = _Plain()

    assert generator.for_areas(AREAS) is generator


def test_several_areas_give_the_loss_ranking_first_and_emissions_second():
    charts = _rank(ROWS)

    assert [chart.title for chart in charts] == [
        "charts.tcl.loss_ranking",
        "charts.tcl.emissions_ranking",
    ]
    assert [chart.position for chart in charts] == [0, 1]
    assert {chart.chart_type for chart in charts} == {"ranked-bar"}
    loss, emissions = charts
    assert (loss.x_axis, loss.y_axis) == ("name", "area_ha")
    assert loss.series_color == LOSS_COLOR
    assert (emissions.x_axis, emissions.y_axis) == (
        "name",
        "carbon_emissions_MgCO2e",
    )
    assert emissions.series_color is None


def test_the_loss_ranking_sums_the_pulled_rows_and_lists_every_area():
    loss = _rank(ROWS)[0]

    assert [
        (r["rank"], r["aoi_id"], r["area_ha"], r["share_pct"])
        for r in loss.chart_data
    ] == [
        (1, "KEN.2", 30.0, 66.67),
        (2, "KEN.1", 15.0, 33.33),
        (3, "KEN.3", 0, 0.0),
    ]


def test_the_ranking_sums_the_rows_it_is_given_without_a_year_filter():
    # The pull asks the API for the requested years; the ranking does not
    # filter by year again.
    rows = [
        {"aoi_id": "KEN.1", "tree_cover_loss_year": 2001, "area_ha": 1.0},
        {"aoi_id": "KEN.2", "tree_cover_loss_year": 2024, "area_ha": 2.0},
        {"aoi_id": "KEN.1", "tree_cover_loss_year": 2024, "area_ha": 4.0},
    ]

    loss = _rank(rows)[0]

    assert {r["aoi_id"]: r["area_ha"] for r in loss.chart_data}["KEN.1"] == 5.0


def test_rows_of_zero_still_count_for_an_area_of_the_ranking():
    rows = ROWS + [
        {
            "aoi_id": "KEN.3",
            "tree_cover_loss_year": 2024,
            "area_ha": 0,
            "carbon_emissions_MgCO2e": 0,
        }
    ]

    loss = _rank(rows)[0]

    assert len(loss.chart_data) == 3


def test_a_pull_with_no_loss_has_no_ranking():
    rows = [
        {"aoi_id": "KEN.1", "area_ha": 0, "carbon_emissions_MgCO2e": 0},
    ]

    assert _rank(rows) == []


def test_no_emissions_anywhere_leaves_only_the_loss_ranking():
    rows = [
        {"aoi_id": "KEN.1", "area_ha": 5.0, "carbon_emissions_MgCO2e": None},
        {"aoi_id": "KEN.2", "area_ha": 3.0, "carbon_emissions_MgCO2e": None},
    ]

    charts = _rank(rows)

    assert [chart.title for chart in charts] == ["charts.tcl.loss_ranking"]


def test_emissions_missing_for_one_area_only_raises():
    rows = [
        {"aoi_id": "KEN.1", "area_ha": 5.0, "carbon_emissions_MgCO2e": 8.0},
        {"aoi_id": "KEN.2", "area_ha": 3.0, "carbon_emissions_MgCO2e": None},
    ]

    with pytest.raises(ValueError):
        _rank(rows)


def test_a_row_of_an_unknown_area_raises():
    rows = ROWS + [{"aoi_id": "KEN.9", "area_ha": 1.0}]

    with pytest.raises(ValueError, match="not in the pull"):
        _rank(rows)


def test_no_areas_give_the_annual_pair():
    charts = TCLChartGenerator().generate(ROWS)

    assert [chart.title for chart in charts] == [
        "charts.tcl.annual_loss",
        "charts.tcl.annual_emissions",
    ]
    assert {chart.chart_type for chart in charts} == {"bar"}


def test_any_areas_given_are_ranked_as_the_gate_owns_the_count():
    one_area_rows = [row for row in ROWS if row["aoi_id"] == "KEN.1"]

    charts = TCLChartGenerator().for_areas([AREAS[0]]).generate(one_area_rows)

    assert [chart.title for chart in charts] == [
        "charts.tcl.loss_ranking",
        "charts.tcl.emissions_ranking",
    ]
