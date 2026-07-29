"""Deterministic table insights for nested analytics results (Land GHG).

RECONSTRUCTED after an accidental ``git clean`` — verify against intent before
relying on it.
"""

from src.agent.subagents.analyst.deterministic import (
    build_table_insights,
    deterministic_narrative,
)


def _nested_result() -> dict:
    return {
        "vegetation": {
            "year": [2016, 2017],
            "land_state_class": ["tree_loss", "tree_loss"],
            "gross_emissions_MgCO2e": [1.0, 2.0],
            "gross_removals_MgCO2": [-0.5, -1.0],
            "net_flux_MgCO2e": [0.5, 1.0],
        },
        "agriculture": {
            "category": ["cropland"],
            "gross_emissions_MgCO2e": [33.0],
        },
    }


def test_build_table_insights_one_table_per_section():
    charts = build_table_insights(_nested_result())
    assert [c.title for c in charts] == ["Vegetation", "Agriculture"]
    assert all(c.chart_type == "table" for c in charts)
    assert [c.position for c in charts] == [0, 1]


def test_build_table_insights_rows_carry_every_source_column():
    charts = build_table_insights(_nested_result())
    veg = charts[0].chart_data
    assert len(veg) == 2
    assert veg[0] == {
        "year": 2016,
        "land_state_class": "tree_loss",
        "gross_emissions_MgCO2e": 1.0,
        "gross_removals_MgCO2": -0.5,
        "net_flux_MgCO2e": 0.5,
    }


def test_build_table_insights_skips_non_column_sections():
    charts = build_table_insights(
        {"vegetation": {"year": [2016]}, "meta": "not-a-table"}
    )
    assert [c.title for c in charts] == ["Vegetation"]


def test_deterministic_narrative_names_sections_and_units():
    text, follow_ups = deterministic_narrative(
        {"dataset_name": "Land GHG Inventory"}, _nested_result()
    )
    assert "vegetation" in text and "agriculture" in text
    assert "MgCO2e" in text
    assert follow_ups == []
