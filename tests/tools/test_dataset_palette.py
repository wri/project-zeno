import re

import pytest

from src.agent.datasets.palette import PALETTES, get_dataset_palette


# This module only exercises pure in-memory catalog parsing and needs no
# database, so override the global autouse DB fixtures with no-ops.
@pytest.fixture(scope="function", autouse=True)
def test_db():
    """Override the global test_db fixture to avoid database connections."""
    pass


@pytest.fixture(scope="function", autouse=True)
def test_db_session():
    """Override the global test_db_session fixture to avoid database connections."""
    pass


@pytest.fixture(scope="function", autouse=True)
def test_db_pool():
    """Override the global test_db_pool fixture to avoid database pool operations."""
    pass


EXPECTED_DATASET_IDS = {0, 1, 2, 3, 4, 5, 6, 7, 8}


def test_all_expected_datasets_have_palettes():
    assert set(PALETTES.keys()) == EXPECTED_DATASET_IDS


def test_get_dataset_palette_unknown_returns_none():
    assert get_dataset_palette(9999) is None


def test_global_land_cover_categories():
    palette = get_dataset_palette(1)
    assert palette is not None
    assert palette["dataset_name"] == "Global land cover"
    slugs = [c["slug"] for c in palette["categories"]]
    assert slugs == [
        "tree_cover",
        "short_vegetation",
        "wetland_short_vegetation",
        "bare_and_sparse_vegetation",
        "water",
        "snow_ice",
        "cropland",
        "cultivated_grasslands",
        "built_up",
    ]
    assert palette["series_color"] is None
    assert palette["divergent_colors"] is None
    assert palette["legend_categories"] is True


def test_sbtn_natural_lands_has_21_categories():
    palette = get_dataset_palette(3)
    assert palette is not None
    assert len(palette["categories"]) == 21
    assert len({c["slug"] for c in palette["categories"]}) == 21


def test_sbtn_natural_lands_opts_out_of_legend_categories():
    """SBTN Natural Lands intentionally curates its map legend down to fewer,
    collapsed rows — the registry still supplies chart colors for all 21
    categories, but the frontend must not expand its legend to match."""
    palette = get_dataset_palette(3)
    assert palette is not None
    assert palette["legend_categories"] is False


def test_tree_cover_loss_by_driver_has_categories_and_series_color():
    palette = get_dataset_palette(8)
    assert palette is not None
    assert len(palette["categories"]) == 8
    assert palette["series_color"] == "#DC6C9A"


def test_tree_cover_loss_series_color():
    palette = get_dataset_palette(4)
    assert palette is not None
    assert palette["categories"] == []
    assert palette["series_color"] == "#DC6C9A"


def test_forest_ghg_net_flux_divergent_colors():
    palette = get_dataset_palette(6)
    assert palette is not None
    assert palette["divergent_colors"] == {
        "positive": "#9a65c0",
        "negative": "#137375",
    }


def test_legend_categories_defaults_true_except_natural_lands():
    for dataset_id, palette in PALETTES.items():
        expected = dataset_id != 3
        assert palette["legend_categories"] is expected, dataset_id


def test_all_colors_are_valid_hex():
    hex_re = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
    for palette in PALETTES.values():
        for category in palette["categories"]:
            assert hex_re.match(category["color"]), category
        if palette["series_color"] is not None:
            assert hex_re.match(palette["series_color"])
        if palette["divergent_colors"] is not None:
            assert hex_re.match(palette["divergent_colors"]["positive"])
            assert hex_re.match(palette["divergent_colors"]["negative"])
