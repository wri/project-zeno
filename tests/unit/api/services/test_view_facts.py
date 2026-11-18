"""Phase 1b of curated charts first: the views' own facts, the generic facts
that each view allows, the rows of an agent view, and a pull with a column
of one value."""

import pytest

from src.agent.subagents.analyst.charts import InsightChart
from src.agent.subagents.analyst.curated_first import chart_fact_sentences
from src.api.services.charts import column_to_rows
from src.api.services.charts.curated import drawn_rows
from src.api.services.charts.view_facts import (
    fires_facts,
    forest_flux_facts,
    gain_facts,
    land_cover_facts,
    natural_lands_facts,
)

# --- column_to_rows ---------------------------------------------------------


def test_a_column_of_one_value_applies_to_every_row():
    # The grasslands API returns "aoi_type": "admin". Zipped as a string,
    # it cut 23 years to 5 rows, one for each character.
    data = {
        "year": list(range(2000, 2023)),
        "area_ha": [1.0] * 23,
        "aoi_type": "admin",
    }
    rows = column_to_rows(data)
    assert len(rows) == 23
    assert {row["aoi_type"] for row in rows} == {"admin"}


def test_columns_of_lists_are_unchanged():
    assert column_to_rows({"a": [1, 2], "b": [3, 4]}) == [
        {"a": 1, "b": 3},
        {"a": 2, "b": 4},
    ]


# --- rows of an agent view --------------------------------------------------


def test_drawn_rows_keep_the_axes_and_the_series():
    chart = InsightChart(
        title="t",
        chart_type="stacked-bar",
        x_axis="year",
        series_fields=["fires", "other"],
        chart_data=[
            {"year": 2020, "fires": 1.0, "other": 2.0, "aoi_id": "X", "co2": 9}
        ],
    )
    assert drawn_rows(chart) == [{"year": 2020, "fires": 1.0, "other": 2.0}]


# --- generic facts that a view allows ---------------------------------------


def _chart(view_id, x_axis, y_axis, rows, chart_type="bar"):
    return InsightChart(
        title="t",
        chart_type=chart_type,
        x_axis=x_axis,
        y_axis=y_axis,
        chart_data=rows,
        view_id=view_id,
    )


def test_grassland_extent_has_no_total_over_years():
    chart = _chart(
        "grasslands.by_year",
        "year",
        "area_ha",
        [{"year": 2000, "area_ha": 100.0}, {"year": 2001, "area_ha": 110.0}],
    )
    sentences = chart_fact_sentences(chart)
    assert not any(s.startswith("Total") for s in sentences)
    assert "Change of area_ha from 2000 to 2001: +10 ha (+10%)." in sentences


def test_tree_cover_extent_has_no_percentages():
    chart = _chart(
        "tree_cover.extent",
        "name",
        "area_ha",
        [{"name": "A", "area_ha": 30.0}, {"name": "B", "area_ha": 10.0}],
    )
    sentences = chart_fact_sentences(chart)
    assert "Rank 1 of area_ha: A, 30 ha." in sentences
    assert not any("%" in s for s in sentences)


def test_forest_flux_has_no_generic_facts():
    chart = _chart(
        "forest_flux.net",
        "flux",
        "carbon_MgCO2e",
        [
            {"flux": "Gross emissions", "carbon_MgCO2e": 10.0},
            {"flux": "Gross removals", "carbon_MgCO2e": -30.0},
            {"flux": "Net flux", "carbon_MgCO2e": -20.0},
        ],
    )
    assert chart_fact_sentences(chart) == []


# --- the views' own facts ---------------------------------------------------


def test_land_cover_agriculture_combines_cropland_and_cultivated_grasslands():
    rows = [
        {"land_cover_class": "Cropland", "area_ha": 30.0},
        {"land_cover_class": "Cultivated grasslands", "area_ha": 10.0},
        {"land_cover_class": "Tree cover", "area_ha": 60.0},
    ]
    assert land_cover_facts(rows) == [
        "Agriculture (cropland and cultivated grasslands): 40 ha, 40% of the "
        "total."
    ]


def test_natural_lands_groups_fold_both_spellings():
    rows = [
        {"natural_lands_class": "Natural forests", "area_ha": 50.0},
        {"natural_lands_class": "Wetland natural forests", "area_ha": 10.0},
        {"natural_lands_class": "Natural short vegetation", "area_ha": 20.0},
        {"natural_lands_class": "Built-up", "area_ha": 15.0},
        {"natural_lands_class": "Cropland", "area_ha": 5.0},
    ]
    assert natural_lands_facts(rows) == [
        "Natural land: 80 ha, 80% of the total.",
        "Non-natural land: 20 ha, 20% of the total.",
        "Natural forest (natural forests, mangroves, wetland natural "
        "forests, natural peat forests): 60 ha, 60% of the total.",
    ]


def test_unclassified_land_is_neither_natural_nor_non_natural():
    rows = [
        {"natural_lands_class": "Natural forests", "area_ha": 50.0},
        {"natural_lands_class": "Cropland", "area_ha": 30.0},
        {"natural_lands_class": "Unclassified", "area_ha": 20.0},
    ]
    assert natural_lands_facts(rows) == [
        "Natural land: 50 ha, 50% of the total.",
        "Non-natural land: 30 ha, 30% of the total.",
        "Unclassified land (neither natural nor non-natural): 20 ha, 20% "
        "of the total.",
        "Natural forest (natural forests, mangroves, wetland natural "
        "forests, natural peat forests): 50 ha, 50% of the total.",
    ]


def test_every_natural_lands_label_of_the_api_has_a_group():
    # The labels of a production pull (Pará, Riau, the Netherlands).
    labels = [
        "Bare", "Built-up", "Cropland", "Mangroves", "Natural forests",
        "Natural peat forests", "Natural peat short vegetation",
        "Natural short vegetation", "Natural water", "Non-natural bare",
        "Non-natural peat short vegetation", "Non-natural peat tree cover",
        "Non-natural short vegetation", "Non-natural tree cover",
        "Non-natural water", "Wetland natural forests",
        "Wetland natural short vegetation",
        "Wetland non-natural short vegetation",
        "Wetland non-natural tree cover",
    ]  # fmt: skip
    rows = [{"natural_lands_class": label, "area_ha": 1.0} for label in labels]
    assert natural_lands_facts(rows)[:2] == [
        "Natural land: 9 ha, 47.37% of the total.",
        "Non-natural land: 10 ha, 52.63% of the total.",
    ]


def test_an_unknown_class_label_raises():
    rows = [{"natural_lands_class": "Moon dust", "area_ha": 1.0}]
    with pytest.raises(ValueError, match="Moon dust"):
        natural_lands_facts(rows)
    rows = [{"land_cover_class": "Moon dust", "area_ha": 1.0}]
    with pytest.raises(ValueError, match="Moon dust"):
        land_cover_facts(rows)


def test_land_cover_labels_of_the_api_match_the_catalog():
    labels = [
        "Bare and sparse vegetation", "Built-up", "Cropland",
        "Cultivated grasslands", "Short vegetation", "Tree cover", "Water",
        "Wetland – short vegetation",
    ]  # fmt: skip
    rows = [{"land_cover_class": label, "area_ha": 1.0} for label in labels]
    assert land_cover_facts(rows) == [
        "Agriculture (cropland and cultivated grasslands): 2 ha, 25% of the "
        "total."
    ]


def test_forest_flux_facts_name_a_net_sink():
    rows = [
        {
            "carbon_net_flux_Mg_CO2e": -1450.5,
            "carbon_gross_emissions_Mg_CO2e": 311.5,
            "carbon_gross_removals_Mg_CO2e": 1762.0,
        }
    ]
    assert forest_flux_facts(rows) == [
        "Gross emissions from 2001 to 2025: 311.50 MgCO2e.",
        "Gross removals from 2001 to 2025: -1762 MgCO2e.",
        "Net flux from 2001 to 2025: -1450.50 MgCO2e.",
        "The area is a net sink (removals > emissions).",
    ]


def test_fires_share_of_the_period():
    rows = [
        {
            "tree_cover_loss_from_fires_area_ha": 10.0,
            "tree_cover_loss_non_fires_area_ha": 30.0,
        },
        {
            "tree_cover_loss_from_fires_area_ha": 15.0,
            "tree_cover_loss_non_fires_area_ha": 45.0,
        },
    ]
    assert fires_facts(rows) == [
        "Loss from fires over the pulled period: 25 ha, 25% of all loss "
        "(100 ha)."
    ]


def test_view_facts_without_rows_are_empty():
    assert land_cover_facts([]) == []
    assert natural_lands_facts([]) == []
    assert forest_flux_facts([]) == []
    assert fires_facts([]) == []


def test_alert_series_take_the_unit_of_the_y_axis():
    chart = InsightChart(
        title="t",
        chart_type="stacked-bar",
        x_axis="alert_date",
        y_axis="area_ha",
        series_fields=["Highest confidence", "High confidence"],
        chart_data=[
            {
                "alert_date": "2026-08-01",
                "Highest confidence": 2.0,
                "High confidence": 5.0,
            },
            {
                "alert_date": "2026-08-02",
                "Highest confidence": 4.0,
                "High confidence": 1.0,
            },
        ],
        view_id="integrated_alerts.by_confidence",
    )
    sentences = chart_fact_sentences(chart)
    assert (
        "Total Highest confidence from 2026-08-01 to 2026-08-02: 6 ha."
        in sentences
    )
    assert "Largest High confidence: 5 ha in 2026-08-01." in sentences
    assert "Total all series: 12 ha." in sentences
    # No change from the first day to the last, and no smallest day.
    assert not any(s.startswith(("Change", "Smallest")) for s in sentences)


def test_gain_periods_have_ranks_and_a_total_with_its_period():
    # The periods do not overlap (confirmed against production and GFW).
    # The pull has only the requested periods, so the total names them.
    rows = [
        {"tree_cover_gain_period": "2010-2015", "area_ha": 30.0},
        {"tree_cover_gain_period": "2015-2020", "area_ha": 10.0},
    ]
    chart = _chart(
        "tree_cover_gain.by_period", "tree_cover_gain_period", "area_ha", rows
    )
    assert chart_fact_sentences(chart, rows) == [
        "Rank 1 of area_ha: 2010-2015, 30 ha, 75% of the total.",
        "Rank 2 of area_ha: 2015-2020, 10 ha, 25% of the total.",
        "Tree cover gain from 2010 to 2020 (the sum of the 2 pulled 5-year "
        "periods): 40 ha.",
    ]
    assert gain_facts([]) == []
