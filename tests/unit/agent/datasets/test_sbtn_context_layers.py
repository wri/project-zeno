"""The SBTN context layers drawn beneath Tree cover loss and Integrated alerts
paint only the classes their analysis counts, in a single colour each, rather
than the standalone card's ten-class breakdown. The tile server leaves values
missing from the colormap transparent, so every other class drops out."""

import json
from urllib.parse import parse_qs, urlsplit

import pytest

from src.agent.datasets.config import DATASETS
from src.agent.datasets.handlers.analytics_handler import (
    INTEGRATED_ALERTS_ID,
    NATURAL_LANDS_ID,
    TREE_COVER_LOSS_ID,
)


def _dataset(dataset_id: int) -> dict:
    return next(d for d in DATASETS if d["dataset_id"] == dataset_id)


def _context_tile_url(dataset_id: int, value: str) -> str:
    return next(
        layer["tile_url"]
        for layer in _dataset(dataset_id)["context_layers"]
        if layer["value"] == value
    )


def _colormap(tile_url: str) -> dict[int, str]:
    """The `colormap` query param as class value -> #RRGGBB."""
    [raw] = parse_qs(urlsplit(tile_url).query)["colormap"]
    return {
        int(value): "#{:02X}{:02X}{:02X}".format(*rgba[:3])
        for value, rgba in json.loads(raw).items()
    }


@pytest.mark.parametrize(
    "dataset_id, value, classes, color",
    [
        # Natural forests (2), mangroves (5), wet natural forests (8) and
        # natural peat forests (9) — the classes the natural_forest_only
        # filter counts.
        (TREE_COVER_LOSS_ID, "natural_forest", [2, 5, 8, 9], "#246E24"),
        # Every natural class (2-11) — the natural_lands filter.
        (INTEGRATED_ALERTS_ID, "natural_lands", list(range(2, 12)), "#A8DDB5"),
    ],
)
def test_context_layer_paints_counted_classes_in_one_colour(
    dataset_id, value, classes, color
):
    colormap = _colormap(_context_tile_url(dataset_id, value))

    assert sorted(colormap) == classes
    assert set(colormap.values()) == {color}


@pytest.mark.parametrize(
    "dataset_id, value",
    [
        (TREE_COVER_LOSS_ID, "natural_forest"),
        (INTEGRATED_ALERTS_ID, "natural_lands"),
    ],
)
def test_context_layer_is_served_from_the_sbtn_raster(dataset_id, value):
    context = urlsplit(_context_tile_url(dataset_id, value))
    card = urlsplit(_dataset(NATURAL_LANDS_ID)["tile_url"])

    assert context.path == card.path
