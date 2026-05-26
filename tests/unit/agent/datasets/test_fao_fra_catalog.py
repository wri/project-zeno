"""Structural tests for the FAO FRA 2025 catalog entry + its 21 context_layers.

These tests don't hit the FAO API — they verify the YAML loads via the
DATASETS registry, satisfies the dataset schema contract, and exposes the
21 variables in the shape `FAOFRAHandler` expects.
"""

from src.agent.datasets.config import (
    CANDIDATE_DATASET_REQUIRED_COLUMNS,
    DATASETS,
)
from src.agent.datasets.handlers.fao_fra_handler import (
    FAO_FRA_2025_DATASET_ID,
)

EXPECTED_VARIABLES = {
    # Forest extent
    "forest_area",
    "forest_area_change",
    "forest_area_protected",
    "permanent_forest_estate",
    # Characteristics
    "forest_characteristics",
    # Growing stock
    "growing_stock",
    "growing_stock_per_ha",
    "growing_stock_composition",
    # Biomass
    "biomass",
    "biomass_per_ha",
    # Carbon
    "carbon_stock",
    "carbon_stock_by_pool",
    "carbon_stock_soil_depth",
    # Management & ownership
    "management_objectives",
    "designated_management",
    "management_rights",
    "ownership",
    # Disturbances
    "disturbances",
    "fire",
    "degraded_forest",
    # Restoration
    "forest_restoration",
}


def _get_fao_entry() -> dict:
    matches = [
        d for d in DATASETS if d["dataset_id"] == FAO_FRA_2025_DATASET_ID
    ]
    assert (
        matches
    ), "FAO FRA 2025 (dataset_id=10) is missing from datasets/catalog/"
    return matches[0]


def test_fao_entry_satisfies_required_columns():
    fao = _get_fao_entry()
    missing = [c for c in CANDIDATE_DATASET_REQUIRED_COLUMNS if c not in fao]
    assert not missing, f"FAO FRA YAML missing required columns: {missing}"


def test_fao_entry_has_no_tile_or_analytics_endpoint():
    """FAO bypasses the analytics pipeline; tile/analytics endpoints must
    stay None so any accidental routing through the analytics handler
    surfaces as a None error, not a silent wrong fetch."""
    fao = _get_fao_entry()
    assert fao.get("tile_url") is None
    assert fao.get("analytics_api_endpoint") is None


def test_fao_entry_has_chart_and_caution_instructions():
    """generate_insights uses these to drive chart wording and rules."""
    fao = _get_fao_entry()
    for key in (
        "code_instructions",
        "presentation_instructions",
        "cautions",
    ):
        assert fao.get(key), f"FAO FRA YAML must define non-empty {key}"


def test_fao_entry_has_citation():
    """The orchestrator's universal citation rule reads this field."""
    fao = _get_fao_entry()
    citation = fao.get("citation") or ""
    assert "FAO" in citation
    assert "doi.org" in citation or "https://" in citation


# ---------------------------------------------------------------------------
# context_layers (the 21 FAO variables)
# ---------------------------------------------------------------------------


def test_context_layers_has_all_21_variables():
    fao = _get_fao_entry()
    layers = fao.get("context_layers") or []
    values = {layer["value"] for layer in layers}
    assert values == EXPECTED_VARIABLES, (
        f"Mismatch in context_layer values. "
        f"Missing: {EXPECTED_VARIABLES - values}. "
        f"Unexpected: {values - EXPECTED_VARIABLES}."
    )


def test_every_context_layer_carries_handler_routing_fields():
    """The handler needs `value`, `description`, `fao_table` on every
    entry plus `fao_variables` (which may be an empty list)."""
    fao = _get_fao_entry()
    for layer in fao["context_layers"]:
        v = layer.get("value")
        assert v, f"context_layer missing `value`: {layer}"
        assert layer.get("description"), f"{v}: missing description"
        assert layer.get("fao_table"), f"{v}: missing fao_table"
        # fao_variables is required (may be empty list)
        assert "fao_variables" in layer, f"{v}: missing fao_variables"
        assert isinstance(
            layer["fao_variables"], list
        ), f"{v}: fao_variables must be a list"


def test_context_layer_values_are_snake_case_identifiers():
    """`value` is used as the LLM-visible identifier and as the state key.
    Keep them snake_case so the LLM can name them confidently."""
    fao = _get_fao_entry()
    for layer in fao["context_layers"]:
        v = layer["value"]
        assert v.islower(), f"{v}: must be lowercase"
        assert "-" not in v, f"{v}: prefer underscores over hyphens"
        assert " " not in v, f"{v}: no spaces in identifiers"


def test_fao_table_names_are_unique_per_value():
    """No two `value`s should map to the same (fao_table, fao_variables)
    pair — that would be a duplicate."""
    fao = _get_fao_entry()
    seen: dict[tuple, str] = {}
    for layer in fao["context_layers"]:
        key = (layer["fao_table"], tuple(layer["fao_variables"]))
        if key in seen:
            raise AssertionError(
                f"Duplicate (fao_table, fao_variables) pair: "
                f"`{layer['value']}` collides with `{seen[key]}`"
            )
        seen[key] = layer["value"]


def test_sparse_coverage_variables_have_explicit_date_ranges():
    """Disturbances and fire have known limited temporal coverage —
    they should declare explicit start/end dates so `revise_date_range`
    surfaces a warning when the user asks outside that window."""
    fao = _get_fao_entry()
    by_value = {layer["value"]: layer for layer in fao["context_layers"]}
    assert by_value["disturbances"].get("start_date") == "2002-01-01"
    assert by_value["disturbances"].get("end_date") == "2020-12-31"
    assert by_value["fire"].get("start_date") == "2007-01-01"
    assert by_value["fire"].get("end_date") == "2019-12-31"


def test_2025_only_variables_carry_explicit_range():
    fao = _get_fao_entry()
    by_value = {layer["value"]: layer for layer in fao["context_layers"]}
    for name in ("growing_stock_composition", "degraded_forest"):
        layer = by_value[name]
        assert layer.get("start_date") == "2025-01-01", name
        assert layer.get("end_date") == "2025-12-31", name
