"""Tests for resolving a catalog dataset into a renderable map layer.

The point of these is parity: the rules moved out of the dataset-selection
subagent so the API recipes could use them, and a tile URL that changes shape
silently breaks every map widget written after it.
"""

import pytest

from src.agent.datasets.handlers.analytics_handler import (
    GRASSLANDS_ID,
    INTEGRATED_ALERTS_ID,
    LAND_COVER_CHANGE_ID,
    TREE_COVER_ID,
    TREE_COVER_LOSS_ID,
)
from src.agent.datasets.layers import (
    DEFAULT_CANOPY_COVER,
    resolve_dataset_layer,
)
from src.shared.config import SharedSettings


def test_integrated_alerts_carries_the_date_range():
    layer = resolve_dataset_layer(
        INTEGRATED_ALERTS_ID, "2026-06-04", "2026-09-02"
    )

    assert layer.dataset_id == INTEGRATED_ALERTS_ID
    assert layer.dataset_name == "Integrated alerts"
    assert "start_date=2026-06-04" in layer.tile_url
    assert "end_date=2026-09-02" in layer.tile_url
    assert layer.start_date == "2026-06-04"
    assert layer.end_date == "2026-09-02"
    # No context layers or parameters exist for this dataset.
    assert layer.context_layers == []
    assert layer.parameters is None


def test_tree_cover_loss_bakes_in_threshold_and_years():
    layer = resolve_dataset_layer(
        TREE_COVER_LOSS_ID,
        "2020-01-01",
        "2024-12-31",
        parameters=[{"name": "canopy_cover", "values": [50]}],
    )

    assert "tree_cover_density_threshold=50" in layer.tile_url
    assert "start_year=2020&end_year=2024" in layer.tile_url
    # The threshold also comes back as a companion layer to draw.
    assert [entry["name"] for entry in layer.context_layers] == [
        "canopy_cover"
    ]
    assert "tcd_50" in layer.context_layers[0]["tile_url"]


def test_tree_cover_loss_falls_back_to_published_years():
    """A period outside the published tiles gets the full range, not a URL
    pointing at tiles that do not exist."""
    layer = resolve_dataset_layer(
        TREE_COVER_LOSS_ID, "2030-01-01", "2030-12-31"
    )

    assert "start_year=2001&end_year=2025" in layer.tile_url


def test_default_threshold_applies_when_no_parameter_is_given():
    layer = resolve_dataset_layer(TREE_COVER_ID, "2000-01-01", "2000-12-31")

    assert f"tcd_{DEFAULT_CANOPY_COVER}" in layer.tile_url
    # Tree cover *is* the threshold layer, so it gets no companion copy.
    assert layer.context_layers == []


@pytest.mark.parametrize("dataset_id", [LAND_COVER_CHANGE_ID, GRASSLANDS_ID])
def test_annual_rasters_resolve_the_year_and_the_eoapi_host(dataset_id):
    layer = resolve_dataset_layer(dataset_id, "2015-01-01", "2020-12-31")

    assert layer.tile_url.startswith(SharedSettings.eoapi_base_url)
    assert "2020" in layer.tile_url
    assert "{year}" not in layer.tile_url


def test_unknown_dataset_is_an_error():
    with pytest.raises(ValueError, match="Dataset not found"):
        resolve_dataset_layer(999999, "2026-01-01", "2026-01-31")
