"""Tests for the map widget config projections in widget_configs.

The projections moved out of add_map_widget without a change in behaviour.
These tests are the ones that tested them in their old place.
"""

from src.api.services.widget_configs import (
    dataset_config,
    default_layer,
    imagery_config,
    migrate_imagery_config,
    widget_config,
)


def _dataset_state():
    """A dataset state dump with render keys plus prose keys to strip."""
    return {
        "dataset_id": 4,
        "dataset_name": "Tree cover loss",
        "tile_url": "https://tiles.example.com/tcl/{z}/{x}/{y}.png?t=30",
        "context_layer": "driver",
        "context_layers": [
            {"name": "driver", "tile_url": "https://tiles.example.com/d.png"}
        ],
        "parameters": [
            {
                "name": "canopy_cover",
                "description": "Minimum canopy density.",
                "values": [30],
            }
        ],
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
        # Prose fields that must never end up in widget config.
        "description": "A long dataset description.",
        "methodology": "Hansen et al.",
        "prompt_instructions": "Do things.",
        "cautions": "Beware.",
        "citation": "Someone 2024",
        "reason": "Best match.",
        "analytics_api_endpoint": "tree-cover-loss",
        "content_date": "2024",
    }


def _multilayer_dataset_state():
    """A multi-layer (e.g. LGMS) dataset state dump — `layers` carries the
    independently-toggleable siblings; `tile_url` mirrors layers[0]."""
    state = _dataset_state()
    state["dataset_id"] = 12
    state["dataset_name"] = "Land GHG Monitoring System (LGMS)"
    state["tile_url"] = "https://tiles.example.com/lgms/lulucf.png"
    state["selected_layer"] = "agriculture"
    state["layers"] = [
        {
            "name": "lulucf",
            "title": "Land use",
            "description": "Net flux.",
            "tile_url": "https://tiles.example.com/lgms/lulucf.png",
            "start_date": None,
            "end_date": None,
        },
        {
            "name": "agriculture",
            "title": "Agriculture",
            "description": "Gross emissions.",
            "tile_url": "https://tiles.example.com/lgms/agriculture.png",
            "start_date": None,
            "end_date": None,
        },
    ]
    return state


def _imagery_state():
    return {
        "provider": "sentinel-2",
        "tile_url": "https://tiles.example.com/mosaic/{z}/{x}/{y}.png?url=x",
        "tilejson_url": "https://tiles.example.com/tilejson.json?url=x",
        "bounds": [-70.0, -10.0, -60.0, 0.0],
        "min_zoom": 5,
        "max_zoom": 15,
        "mosaic_id": "abc123",
        "item_count": 12,
        "start_date": "2024-05-28",
        "end_date": "2024-06-04",
        "mean_cloud_cover": 8.5,
        "min_cloud_cover": 2.1,
        "max_cloud_cover_observed": 15.3,
        "max_cloud_cover": 20,
        "target_date": "2024-06-01",
        "window_days": 7,
        "aoi_names": ["Paraná"],
    }


def test_dataset_config_date_fallback_to_state():
    dataset = _dataset_state()
    dataset["start_date"] = None
    dataset["end_date"] = None
    state = {
        "dataset": dataset,
        "start_date": "2023-01-01",
        "end_date": "2023-12-31",
    }
    config = dataset_config(state)
    assert config["start_date"] == "2023-01-01"
    assert config["end_date"] == "2023-12-31"


def test_dataset_config_none_without_tile_url():
    assert dataset_config({}) is None
    assert dataset_config({"dataset": {"tile_url": ""}}) is None
    assert dataset_config({"dataset": {"tile_url": "", "layers": []}}) is None


def test_dataset_config_derives_tile_url_from_layers_when_absent():
    """The renderability check and tile_url mirror work from `layers` alone
    when the top-level tile_url is empty — no upstream resolution needed."""
    state = {
        "dataset": {
            "dataset_id": 12,
            "dataset_name": "LGMS",
            "tile_url": "",
            "layers": [
                {
                    "name": "lulucf",
                    "tile_url": "https://tiles.example.com/a.png",
                }
            ],
        }
    }
    config = dataset_config(state)
    assert config is not None
    assert config["tile_url"] == "https://tiles.example.com/a.png"


def test_dataset_config_fallback_prefers_selected_layer_over_layers_zero():
    """When tile_url is missing and layers[]-alone must supply it, the
    fallback matches what the agent actually selected — not just layers[0]."""
    state = {
        "dataset": {
            "dataset_id": 12,
            "dataset_name": "LGMS",
            "tile_url": "",
            "selected_layer": "agriculture",
            "layers": [
                {
                    "name": "lulucf",
                    "tile_url": "https://tiles.example.com/a.png",
                },
                {
                    "name": "agriculture",
                    "tile_url": "https://tiles.example.com/b.png",
                },
            ],
        }
    }
    config = dataset_config(state)
    assert config["tile_url"] == "https://tiles.example.com/b.png"


def test_default_layer_matches_selected_name():
    layers = [
        {"name": "lulucf", "tile_url": "https://x/a.png"},
        {"name": "agriculture", "tile_url": "https://x/b.png"},
    ]
    assert default_layer(layers, "agriculture") == layers[1]


def test_default_layer_falls_back_to_first_when_unset_or_unmatched():
    layers = [
        {"name": "lulucf", "tile_url": "https://x/a.png"},
        {"name": "agriculture", "tile_url": "https://x/b.png"},
    ]
    assert default_layer(layers, None) == layers[0]
    assert default_layer(layers, "nonexistent") == layers[0]
    assert default_layer(None, "agriculture") is None
    assert default_layer([], "agriculture") is None


def test_dataset_config_carries_multilayer_layers_through():
    """A multi-layer dataset's (e.g. LGMS) independently-toggleable siblings
    must survive the widget-config snapshot, not just the legacy tile_url."""
    state = {"dataset": _multilayer_dataset_state()}
    config = dataset_config(state)
    assert config["layers"] == [
        {
            "name": "lulucf",
            "title": "Land use",
            "description": "Net flux.",
            "tile_url": "https://tiles.example.com/lgms/lulucf.png",
            "start_date": None,
            "end_date": None,
        },
        {
            "name": "agriculture",
            "title": "Agriculture",
            "description": "Gross emissions.",
            "tile_url": "https://tiles.example.com/lgms/agriculture.png",
            "start_date": None,
            "end_date": None,
        },
    ]
    # A non-empty top-level tile_url passes through verbatim — selected_layer
    # only kicks in via default_layer when tile_url itself is empty (see
    # test_dataset_config_fallback_prefers_selected_layer_over_layers_zero).
    assert config["tile_url"] == "https://tiles.example.com/lgms/lulucf.png"


def test_imagery_config_none_without_essentials():
    assert imagery_config({}) is None
    assert imagery_config({"imagery": {"tile_url": "x"}}) is None
    assert imagery_config({"imagery": {"mosaic_id": "x"}}) is None


def test_imagery_config_includes_cloud_cover():
    """Cloud cover fields are included in the widget config snapshot."""
    state = {"imagery": _imagery_state()}
    config = imagery_config(state)
    assert config["mean_cloud_cover"] == 8.5
    assert config["min_cloud_cover"] == 2.1
    assert config["max_cloud_cover_observed"] == 15.3
    assert config["max_cloud_cover"] == 20
    assert config["bounds"] == [-70.0, -10.0, -60.0, 0.0]
    assert config["min_zoom"] == 5
    assert config["max_zoom"] == 15


def test_widget_config_wraps_one_layer_and_optional_title():
    assert widget_config("imagery", {"tile_url": "x"}, None) == {
        "default_view": "map",
        "imagery": {"tile_url": "x"},
    }
    assert widget_config("dataset", {"tile_url": "x"}, "Alerts") == {
        "default_view": "map",
        "dataset": {"tile_url": "x"},
        "title": "Alerts",
    }


CLIENT_IMAGERY = {
    "provider": "sentinel-2",
    "render": "client",
    "mosaic_id": "tok",
    "target_date": "2026-11-10",
    "window_days": 7,
    "max_cloud_cover": 20,
    "aoi_names": ["Jaru"],
}


def test_imagery_config_accepts_client_imagery_without_tile_url():
    config = imagery_config({"imagery": CLIENT_IMAGERY})
    assert config["render"] == "client"
    assert config["mosaic_id"] == "tok"
    assert config["tile_url"] is None


def test_imagery_config_rejects_client_imagery_without_mosaic_id():
    imagery = {**CLIENT_IMAGERY, "mosaic_id": None}
    assert imagery_config({"imagery": imagery}) is None


# A recipe token (see tests/unit/shared/test_imagery_recipe.py).
LEGACY_TOKEN = (
    "eyJhIjpbWyJnYWRtIiwiUEVSLjExLjNfMSJdLFsia2JhIiwiUGFjYXlhLVNhbWlyaWEg"
    "XHUwMGU5Il1dLCJjIjo1MCwiZCI6IjIwMjYtMDYtMTUiLCJuIjo1MCwidyI6MzB9"
)


def test_migrate_moves_a_legacy_mosaic_to_client_rendering():
    legacy = {
        "default_view": "map",
        "title": "Imagery",
        "imagery": {
            "provider": "sentinel-2",
            "tile_url": "https://tiles.globalforestwatch.org/cog/mosaic/x",
            "tilejson_url": "https://tiles.globalforestwatch.org/t.json",
            "mosaic_id": LEGACY_TOKEN,
            "item_count": 9,
            "target_date": "2026-06-15",
            "window_days": 30,
            "max_cloud_cover": 50,
            "aoi_names": ["Paracas", "Pacaya-Samiria"],
        },
    }
    migrated = migrate_imagery_config(legacy)
    assert migrated == {
        "default_view": "map",
        "title": "Imagery",
        "imagery": {
            "provider": "sentinel-2",
            "render": "client",
            "mosaic_id": LEGACY_TOKEN,
            "target_date": "2026-06-15",
            "window_days": 30,
            "max_cloud_cover": 50,
            "aoi_names": ["Paracas", "Pacaya-Samiria"],
        },
    }
    # The input is not mutated.
    assert legacy["imagery"]["tile_url"]


def test_migrate_leaves_other_widgets_alone():
    assert migrate_imagery_config(None) is None
    assert migrate_imagery_config({"dataset": {"tile_url": "x"}}) is None
    planet = {"imagery": {"provider": "planet", "mosaic_id": LEGACY_TOKEN}}
    assert migrate_imagery_config(planet) is None
    assert migrate_imagery_config({"imagery": CLIENT_IMAGERY}) is None
    not_a_recipe = {"imagery": {"tile_url": "x", "mosaic_id": "abc123"}}
    assert migrate_imagery_config(not_a_recipe) is None
