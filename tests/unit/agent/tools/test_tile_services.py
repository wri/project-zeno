"""get_tile_services_for_dataset scopes the tile URL to the requested date
range, using the convention the dataset declares in its catalog YAML
(`tile_date_filter`) rather than a hardcoded list of dataset ids."""

from types import SimpleNamespace

from src.agent.datasets.config import DATASETS
from src.agent.datasets.handlers.analytics_handler import (
    INTEGRATED_ALERTS_ID,
    LAND_COVER_CHANGE_ID,
    TREE_COVER_LOSS_ID,
)
from src.agent.datasets.layers import (
    DATE_PARAMS,
    YEAR_IN_PATH,
    YEAR_PARAMS,
)
from src.agent.subagents.pick_dataset.tool import (
    get_tile_services_for_dataset,
)

IA_TILE = (
    "https://tiles.globalforestwatch.org/gfw_integrated_dist_alerts/latest/"
    "dynamic/{z}/{x}/{y}.png?render_type=true_color"
)


def _row(dataset_id, tile_url, date_filter, parameters=None):
    return SimpleNamespace(
        dataset_id=dataset_id,
        tile_url=tile_url,
        tile_date_filter=date_filter,
        context_layers=None,
        parameters=parameters,
    )


def _selection(dataset_id):
    return SimpleNamespace(
        dataset_id=dataset_id, context_layer=None, parameters=None
    )


def test_integrated_alerts_tile_url_gets_date_params():
    tile_url, context_layers = get_tile_services_for_dataset(
        _selection(INTEGRATED_ALERTS_ID),
        _row(INTEGRATED_ALERTS_ID, IA_TILE, DATE_PARAMS),
        "2024-03-01",
        "2024-10-31",
    )

    assert "start_date=2024-03-01" in tile_url
    assert "end_date=2024-10-31" in tile_url
    assert tile_url.startswith(IA_TILE)  # date params appended, base preserved
    assert context_layers == []


def test_year_params_layer_gets_year_granular_bounds():
    """Annual tree cover loss filters by year, not by date."""
    tile_url, _ = get_tile_services_for_dataset(
        _selection(TREE_COVER_LOSS_ID),
        _row(
            TREE_COVER_LOSS_ID,
            "https://tiles.example.org/tcl/{z}/{x}/{y}.png?tcd={threshold}",
            YEAR_PARAMS,
            # Tree cover loss also carries a canopy-cover threshold, whose
            # own layer comes back as a context layer.
            parameters=[
                {
                    "name": "canopy_cover",
                    "tile_url": "https://tiles.example.org/tcd_{threshold}/{z}/{x}/{y}.png",
                }
            ],
        ),
        "2015-06-01",
        "2020-02-28",
    )

    assert "&start_year=2015&end_year=2020" in tile_url
    assert "start_date=" not in tile_url


def test_year_in_path_layer_substitutes_the_end_year():
    """Annual rasters name the year in the item path instead of filtering."""
    tile_url, _ = get_tile_services_for_dataset(
        _selection(LAND_COVER_CHANGE_ID),
        _row(
            LAND_COVER_CHANGE_ID,
            "https://tiles.example.org/items/land-cover-{year}/{{z}}/{{x}}/{{y}}.png",
            YEAR_IN_PATH,
        ),
        "2015-01-01",
        "2024-12-31",
    )

    assert tile_url == (
        "https://tiles.example.org/items/land-cover-2024/{z}/{x}/{y}.png"
    )


def test_layer_without_a_date_convention_is_left_alone():
    bare = "https://tiles.example.org/gain/{z}/{x}/{y}.png"

    tile_url, _ = get_tile_services_for_dataset(
        _selection(5),
        _row(5, bare, None),
        "2001-01-01",
        "2020-12-31",
    )

    assert tile_url == bare


def test_every_catalog_date_convention_is_exercised_above():
    """Guard against a new convention landing with no coverage here."""
    declared = {
        d.get("tile_date_filter")
        for d in DATASETS
        if d.get("tile_date_filter")
    }

    assert declared == {DATE_PARAMS, YEAR_PARAMS, YEAR_IN_PATH}
