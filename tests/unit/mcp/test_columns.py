"""columns.json: the columns of every dataset's rows, captured from the
analytics API, which the charting skill lists."""

import pytest

from src.agent.datasets.handlers.analytics_handler import LAND_COVER_CHANGE_ID
from src.mcp.columns import COLUMN_NOTES, load, unit_of
from src.mcp.datasets import available_datasets, get_catalog_dataset
from src.mcp.skill import _chart_rules, _misnamed_columns

COLUMNS = load()


@pytest.mark.parametrize(
    "ds", available_datasets(), ids=lambda ds: str(ds["dataset_id"])
)
def test_every_dataset_and_context_layer_has_its_columns(ds):
    variants = COLUMNS.get(str(ds["dataset_id"]))
    assert variants, "run: uv run python -m src.mcp.columns"
    expected = {"default"} | {
        f"context_layer={layer['value']}"
        for layer in ds.get("context_layers") or []
    }
    if ds["dataset_id"] == LAND_COVER_CHANGE_ID:
        expected.add("change_over_time")
    assert set(variants) == expected
    for name, variant in variants.items():
        assert "columns" in variant, f"{name}: {variant.get('error')}"


def test_every_column_is_described():
    columns = {
        column
        for variants in COLUMNS.values()
        for variant in variants.values()
        for column in variant["columns"]
    }
    # A new column needs a word in COLUMN_NOTES before the skill lists it.
    assert columns - set(COLUMN_NOTES) == set()


@pytest.mark.parametrize(
    "column, unit",
    [
        ("area_ha", "ha"),
        ("carbon_emissions_MgCO2e", "MgCO2e"),
        ("carbon_net_flux_Mg_CO2e", "MgCO2e"),
        ("emissions_factor_tCO2e_per_tonne_production", "tCO2e/t"),
        ("emissions_tCO2e", "tCO2e"),
        ("production_tonnes", "t"),
        ("tree_cover_loss_year", ""),
    ],
)
def test_a_columns_unit_comes_from_its_name(column, unit):
    assert unit_of(column) == unit


def test_the_skill_names_the_columns_the_rules_misspell():
    # The catalog's SLUC rules say emissions_tco2e; the rows have
    # emissions_tCO2e.
    ds = get_catalog_dataset(9)
    assert ("emissions_tco2e", "emissions_tCO2e") in _misnamed_columns(
        ds, str(ds["code_instructions"])
    )
    rules = _chart_rules(ds)
    assert "`emissions_tco2e` is `emissions_tCO2e`" in rules
    assert "where they say REFUSE, decline that request" in rules


def test_options_and_words_are_not_taken_for_columns():
    ds = get_catalog_dataset(4)
    assert (
        _misnamed_columns(ds, "primary_forest canopy_cover is_natural") == []
    )
