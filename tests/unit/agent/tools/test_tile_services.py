"""get_tile_services_for_dataset appends the requested date range to the tile
URL for date-driven alert layers (Integrated alerts), so the map shows alerts
only within the queried window.

The deprecated top-level tile_url mirror is always just selected_row.tile_url
(plus the mutations below) — selected_layer never resolves it here. That
resolution (selected_layer, falling back to layers[0]) lives entirely in
add_map_widget.py's _default_layer, at persistence time, where a single
tile_url is actually required. Readers of the live agent response (e.g.
pickDataset.ts) check `layers` themselves for a multi-layer dataset."""

from types import SimpleNamespace

from src.agent.datasets.handlers.analytics_handler import (
    INTEGRATED_ALERTS_ID,
    TREE_COVER_LOSS_ID,
)
from src.agent.subagents.pick_dataset.tool import (
    get_dataset_layers,
    get_tile_services_for_dataset,
)

IA_TILE = (
    "https://tiles.globalforestwatch.org/gfw_integrated_alerts/latest/"
    "dynamic/{z}/{x}/{y}.png?render_type=true_color"
)


def test_integrated_alerts_tile_url_gets_date_params():
    selection = SimpleNamespace(
        dataset_id=INTEGRATED_ALERTS_ID,
        context_layer=None,
        selected_layer=None,
        parameters=None,
    )
    row = SimpleNamespace(
        dataset_id=INTEGRATED_ALERTS_ID,
        dataset_name="Integrated alerts",
        tile_url=IA_TILE,
        context_layers=None,
        parameters=None,
    )

    tile_url, context_layers, layers = get_tile_services_for_dataset(
        selection, row, "2024-03-01", "2024-10-31"
    )

    assert "start_date=2024-03-01" in tile_url
    assert "end_date=2024-10-31" in tile_url
    assert tile_url.startswith(IA_TILE)  # date params appended, base preserved
    assert context_layers == []
    # No explicit `layers` on the yml row → auto-derived as a single entry
    # mirroring the resolved tile_url, so single-layer datasets are unaffected.
    assert len(layers) == 1
    assert layers[0].tile_url == tile_url
    assert layers[0].name == "Integrated alerts"


def test_multilayer_dataset_returns_all_layers():
    """A dataset row with an explicit `layers` list (e.g. LGMS) always
    returns every declared layer, not just a single-entry auto-derivation —
    independent of the deprecated tile_url mirror, and independent of
    selected_layer (which this function no longer resolves tile_url from)."""
    lgms_tile = "https://tiles.globalforestwatch.org/lgms/{z}/{x}/{y}.png"
    selection = SimpleNamespace(
        dataset_id=12,
        context_layer=None,
        selected_layer="agriculture",
        parameters=None,
    )
    row = SimpleNamespace(
        dataset_id=12,
        dataset_name="LGMS",
        tile_url=lgms_tile,
        context_layers=None,
        parameters=None,
        layers=[
            {"name": "lulucf", "tile_url": lgms_tile},
            {"name": "agriculture", "tile_url": lgms_tile + "?x=1"},
        ],
    )

    tile_url, _, layers = get_tile_services_for_dataset(
        selection, row, "2024-01-01", "2024-12-31"
    )

    # tile_url mirrors the row's own field verbatim — selected_layer plays
    # no part in it here, regardless of what it's set to.
    assert tile_url == lgms_tile
    assert [layer.name for layer in layers] == ["lulucf", "agriculture"]


def test_no_layers_falls_back_to_raw_tile_url():
    """A dataset row with no `layers` at all (every non-LGMS catalog entry)
    resolves tile_url from its own field, unaffected by selected_layer."""
    selection = SimpleNamespace(
        dataset_id=INTEGRATED_ALERTS_ID,
        context_layer=None,
        selected_layer="agriculture",
        parameters=None,
    )
    row = SimpleNamespace(
        dataset_id=INTEGRATED_ALERTS_ID,
        dataset_name="Integrated alerts",
        tile_url=IA_TILE,
        context_layers=None,
        parameters=None,
    )

    tile_url, _, _ = get_tile_services_for_dataset(
        selection, row, "2024-01-01", "2024-12-31"
    )

    assert tile_url.startswith(IA_TILE)


def test_get_dataset_layers_empty_for_analytics_only_dataset():
    """No `layers` and no tile_url (a genuinely analytics-only dataset) must
    not manufacture a placeholder DatasetLayer with an empty tile_url — an
    empty list correctly signals "nothing to render", matching the
    (also empty) legacy tile_url mirror for the same dataset."""
    row = SimpleNamespace(dataset_name="Analytics only")
    assert get_dataset_layers(row, "") == []


def test_get_dataset_layers_single_entry_for_ordinary_dataset():
    row = SimpleNamespace(dataset_name="Tree cover loss")
    layers = get_dataset_layers(row, "https://tiles.example.com/tcl.png")
    assert len(layers) == 1
    assert layers[0].name == "Tree cover loss"
    assert layers[0].tile_url == "https://tiles.example.com/tcl.png"


def test_analytics_only_dataset_returns_no_layers_end_to_end():
    """An analytics-only dataset (no tile_url, no `layers` in the yml) gets
    an empty `layers` list from get_tile_services_for_dataset, not a
    single useless entry with an empty tile_url."""
    selection = SimpleNamespace(
        dataset_id=99, context_layer=None, selected_layer=None, parameters=None
    )
    row = SimpleNamespace(
        dataset_id=99,
        dataset_name="Analytics only",
        tile_url="",
        context_layers=None,
        parameters=None,
    )

    tile_url, _, layers = get_tile_services_for_dataset(
        selection, row, "2024-01-01", "2024-12-31"
    )

    assert tile_url == ""
    assert layers == []


def test_canopy_cover_threshold_substitution():
    """The {threshold} substitution reads the already-resolved local
    `tile_url`, not a second selected_row.tile_url access."""
    selection = SimpleNamespace(
        dataset_id=TREE_COVER_LOSS_ID,
        context_layer=None,
        selected_layer=None,
        parameters=None,
    )
    row = SimpleNamespace(
        dataset_id=TREE_COVER_LOSS_ID,
        dataset_name="Tree cover loss",
        tile_url="https://tiles.example.com/tcl/{threshold}/{z}.png",
        context_layers=None,
        parameters=[
            {
                "name": "canopy_cover",
                "tile_url": "https://tiles.example.com/ctx/{threshold}.png",
            }
        ],
    )

    tile_url, context_layers, _ = get_tile_services_for_dataset(
        selection, row, "2024-01-01", "2024-12-31"
    )

    assert tile_url == (
        "https://tiles.example.com/tcl/30/{z}.png"
        "&start_year=2024&end_year=2024"
    )
    assert context_layers[0].tile_url == "https://tiles.example.com/ctx/30.png"
