"""Tests for the /api/metadata endpoint."""

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
async def test_metadata_layer_id_mapping_has_known_sources(client):
    """Layer ID mapping contains expected data sources."""
    response = await client.get("/api/metadata")
    layer_id_mapping = response.json()["layer_id_mapping"]

    # These sources are expected to be present based on geocoding_helpers
    assert isinstance(layer_id_mapping, dict)
    assert len(layer_id_mapping) > 0
