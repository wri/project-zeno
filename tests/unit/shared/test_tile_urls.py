"""Host-less persistence of widget tile URLs (src/shared/tile_urls.py).

Persisted absolute tile URLs orphan every map widget when the eoapi host
rotates — a browser-side-only failure with no server signal. Configs are
stored with a relative tile_path and reassembled against the currently
configured host on read; foreign-host layers pass through untouched.
"""

from src.shared import tile_urls
from src.shared.config import SharedSettings
from src.shared.tile_urls import (
    absolutize_widget_config,
    relativize_widget_config,
)

BASE = SharedSettings.eoapi_base_url.rstrip("/")


def test_eoapi_tile_url_stored_as_path():
    config = {
        "default_view": "map",
        "dataset": {
            "dataset_name": "TCL",
            "tile_url": f"{BASE}/raster/tiles/{{z}}/{{x}}/{{y}}.png?x=1",
        },
    }
    stored = relativize_widget_config(config)
    assert stored["dataset"]["tile_path"] == (
        "/raster/tiles/{z}/{x}/{y}.png?x=1"
    )
    assert "tile_url" not in stored["dataset"]
    # Input is never mutated: callers pass request bodies and agent state.
    assert "tile_url" in config["dataset"]


def test_foreign_host_tile_url_kept_verbatim():
    config = {
        "imagery": {
            "tile_url": "https://tiles.globalforestwatch.org/m/{z}/{x}/{y}",
            "mosaic_id": "abc",
        }
    }
    assert relativize_widget_config(config) == config
    assert absolutize_widget_config(config) == config


def test_round_trip_serves_currently_configured_host(monkeypatch):
    stored = relativize_widget_config(
        {"dataset": {"tile_url": f"{BASE}/raster/tiles/{{z}}.png"}}
    )
    monkeypatch.setattr(
        tile_urls.SharedSettings,
        "eoapi_base_url",
        "https://eoapi-next.example.org",
    )
    served = absolutize_widget_config(stored)
    assert served["dataset"]["tile_url"] == (
        "https://eoapi-next.example.org/raster/tiles/{z}.png"
    )


def test_legacy_absolute_config_served_unchanged():
    """Rows written before tile_path existed keep their absolute URL."""
    config = {"dataset": {"tile_url": f"{BASE}/raster/tiles/{{z}}.png"}}
    assert absolutize_widget_config(config) == config


def test_empty_and_layerless_configs_pass_through():
    assert relativize_widget_config(None) is None
    assert absolutize_widget_config({}) == {}
    text = {"text": "# Notes"}
    assert relativize_widget_config(text) == text
    malformed = {"dataset": "not-a-dict"}
    assert relativize_widget_config(malformed) == malformed
