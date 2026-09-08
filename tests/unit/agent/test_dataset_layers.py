"""The map-layer registry derived from the catalog YAMLs.

`tile_date_filter` is the one place the date convention is declared: the agent
reads it to build the tile URL it puts on the map, and /api/datasets/catalog
serves it to clients that add layers outside a conversation. A typo or a URL
that cannot carry its filter has to fail at import, not at render time.
"""

import pytest

from src.agent.datasets import layers as layers_module
from src.agent.datasets.layers import (
    DATE_PARAMS,
    LAYERS,
    NO_DATE_FILTER,
    YEAR_IN_PATH,
    get_dataset_layer,
)

_ALERTS = 11


def _catalog_entry(**overrides) -> dict:
    entry = {
        "dataset_id": 99,
        "dataset_name": "Test dataset",
        "tile_url": "https://tiles.example.org/x/{z}/{x}/{y}.png?render=true",
        "start_date": "2020-01-01",
    }
    entry.update(overrides)
    return entry


def _build(entry: dict, monkeypatch) -> dict:
    monkeypatch.setattr(layers_module, "DATASETS", [entry])
    return layers_module._build_layers()


def test_datasets_without_tiles_are_omitted():
    """sLUC emission factors (9) and LGMS (12) have an empty tile_url."""
    assert 9 not in LAYERS
    assert 12 not in LAYERS
    assert get_dataset_layer(9) is None


def test_integrated_alerts_declares_day_granular_filtering():
    alerts = get_dataset_layer(_ALERTS)

    assert alerts is not None
    assert alerts["date_filter"] == DATE_PARAMS
    assert alerts["end_date"] is None
    assert alerts["tile_url"].startswith("https://")


def test_relative_tile_urls_are_absolutised(monkeypatch):
    layer = _build(
        _catalog_entry(tile_url="/raster/collections/x/{z}/{x}/{y}.png"),
        monkeypatch,
    )[99]

    assert layer["tile_url"].startswith("http")
    assert "//raster" not in layer["tile_url"]


def test_year_in_path_urls_are_unescaped(monkeypatch):
    """The YAML doubles the tile-scheme braces so str.format can fill {year};
    clients get them single."""
    layer = _build(
        _catalog_entry(
            tile_url="https://t.example.org/items/x-{year}/{{z}}/{{x}}/{{y}}.png",
            tile_date_filter=YEAR_IN_PATH,
        ),
        monkeypatch,
    )[99]

    assert layer["tile_url"] == (
        "https://t.example.org/items/x-{year}/{z}/{x}/{y}.png"
    )


def test_absent_convention_means_no_filter(monkeypatch):
    layer = _build(_catalog_entry(), monkeypatch)[99]

    assert layer["date_filter"] == NO_DATE_FILTER
    assert layer["threshold_values"] is None
    assert layer["default_threshold"] is None


def test_unknown_convention_is_rejected(monkeypatch):
    with pytest.raises(ValueError, match="unknown tile_date_filter"):
        _build(_catalog_entry(tile_date_filter="last_two_weeks"), monkeypatch)


def test_query_param_filter_needs_a_query_string(monkeypatch):
    """The agent appends these with `&`, so a URL with no `?` would 404."""
    with pytest.raises(ValueError, match="no query string"):
        _build(
            _catalog_entry(
                tile_url="https://t.example.org/x/{z}/{x}/{y}.png",
                tile_date_filter=DATE_PARAMS,
            ),
            monkeypatch,
        )


def test_year_in_path_needs_a_year_placeholder(monkeypatch):
    with pytest.raises(ValueError, match="needs a .year. placeholder"):
        _build(
            _catalog_entry(
                tile_url="https://t.example.org/x/{{z}}/{{x}}/{{y}}.png",
                tile_date_filter=YEAR_IN_PATH,
            ),
            monkeypatch,
        )


def test_threshold_placeholder_needs_declared_values(monkeypatch):
    with pytest.raises(ValueError, match="no canopy_cover parameter values"):
        _build(
            _catalog_entry(
                tile_url="https://t.example.org/tcd_{threshold}/{z}/{x}/{y}.png",
                parameters=[{"name": "something_else", "values": [1]}],
            ),
            monkeypatch,
        )
