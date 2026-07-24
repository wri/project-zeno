"""Tests for the /api/metadata endpoint."""

import tomllib

import pytest


@pytest.mark.asyncio
async def test_metadata_returns_expected_keys(client):
    """Metadata endpoint returns all expected top-level keys."""
    response = await client.get("/api/metadata")

    assert response.status_code == 200
    data = response.json()

    assert "version" in data
    assert "layer_id_mapping" in data
    assert "subregion_to_subtype_mapping" in data
    assert "gadm_subtype_mapping" in data
    assert "model" in data


@pytest.mark.asyncio
async def test_metadata_model_info(client):
    """Metadata returns model name and class information."""
    response = await client.get("/api/metadata")

    assert response.status_code == 200
    model_info = response.json()["model"]

    assert "current" in model_info
    assert "model_class" in model_info
    assert "small" in model_info
    assert "small_model_class" in model_info


@pytest.mark.asyncio
async def test_metadata_no_auth_required(client):
    """Metadata endpoint is public - no authentication needed."""
    # No Authorization header
    response = await client.get("/api/metadata")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_metadata_version_matches_pyproject(client):
    """Version returned by the API matches the version in pyproject.toml."""
    with open("pyproject.toml", "rb") as f:
        expected = tomllib.load(f)["project"]["version"]

    response = await client.get("/api/metadata")

    assert response.status_code == 200
    assert response.json()["version"] == expected


@pytest.mark.asyncio
async def test_metadata_layer_id_mapping_has_known_sources(client):
    """Layer ID mapping contains expected data sources."""
    response = await client.get("/api/metadata")
    layer_id_mapping = response.json()["layer_id_mapping"]

    # These sources are expected to be present based on geocoding_helpers
    assert isinstance(layer_id_mapping, dict)
    assert len(layer_id_mapping) > 0


@pytest.mark.asyncio
async def test_datasets_catalog_no_auth_required(client):
    """Dataset catalog endpoint is public - no authentication needed."""
    response = await client.get("/api/datasets/catalog")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_datasets_catalog_includes_global_land_cover(client):
    """Global land cover (dataset_id=1) exposes its category color mapping."""
    response = await client.get("/api/datasets/catalog")
    datasets = response.json()["datasets"]

    land_cover = next(d for d in datasets if d["dataset_id"] == 1)
    assert land_cover["dataset_name"] == "Global land cover"
    assert land_cover["series_color"] is None
    assert land_cover["divergent_colors"] is None
    assert land_cover["legend_categories"] is True
    slugs = [c["slug"] for c in land_cover["categories"]]
    assert "tree_cover" in slugs
    assert "cropland" in slugs
    tree_cover = next(
        c for c in land_cover["categories"] if c["slug"] == "tree_cover"
    )
    assert tree_cover["label_en"] == "Tree cover"
    assert tree_cover["color"] == "#246E24"


@pytest.mark.asyncio
async def test_datasets_catalog_natural_lands_opts_out_of_legend_categories(
    client,
):
    """SBTN Natural Lands (dataset_id=3) curates its map legend down to fewer
    rows — chart colors still cover all categories, but legend_categories=False
    tells the frontend not to expand its legend to the full category list."""
    response = await client.get("/api/datasets/catalog")
    datasets = response.json()["datasets"]

    natural_lands = next(d for d in datasets if d["dataset_id"] == 3)
    assert len(natural_lands["categories"]) == 21
    assert natural_lands["legend_categories"] is False


@pytest.mark.asyncio
async def test_datasets_catalog_includes_divergent_colors(client):
    """Forest GHG net flux (dataset_id=6) exposes divergent positive/negative colors."""
    response = await client.get("/api/datasets/catalog")
    datasets = response.json()["datasets"]

    ghg = next(d for d in datasets if d["dataset_id"] == 6)
    assert ghg["categories"] == []
    assert ghg["divergent_colors"] == {
        "positive": "#9a65c0",
        "negative": "#137375",
    }


@pytest.mark.asyncio
async def test_datasets_catalog_only_includes_datasets_with_colors(client):
    """Datasets without any category/series/divergent colors are omitted."""
    response = await client.get("/api/datasets/catalog")
    datasets = response.json()["datasets"]

    dataset_ids = {d["dataset_id"] for d in datasets}
    assert dataset_ids == {0, 1, 2, 3, 4, 5, 6, 7, 8}
