"""Phase 1b of curated charts first: the views' own facts, the generic facts
that each view allows, the rows of an agent view, and a pull with a column
of one value."""

from src.agent.subagents.analyst.charts import InsightChart
from src.agent.subagents.analyst.curated_first import chart_fact_sentences
from src.api.services.charts import column_to_rows
from src.api.services.charts.curated import drawn_rows
from src.api.services.charts.view_facts import (
    fires_facts,
    forest_flux_facts,
    is_natural,
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
    assert is_natural("wet natural forests")
    assert not is_natural("non-natural tree cover")
    assert not is_natural("built")
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
