"""Tests for automatic area naming endpoint."""

from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest

from src.api import app as api


@contextmanager
def domain_allowlist(domains: str):
    """Context manager to set and reset DOMAINS_ALLOWLIST."""
    domain_list = domains.split(",")
    try:
        with patch.object(api.APISettings, "domains_allowlist_str", domains):
            yield domain_list
    finally:
        pass  # Patch is automatically reverted


@pytest.mark.asyncio
async def test_custom_area_name_requires_auth(client):
    """Test that automatic area naming requires authentication."""
    test_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
                },
                "properties": {},
            }
        ],
    }

    response = await client.post("/api/custom_area_name", json=test_geojson)
    assert response.status_code == 401
    assert "Missing Bearer token" in response.json()["detail"]


@pytest.mark.asyncio
async def test_custom_area_name_success(client, auth_override):
    """Test successful automatic area naming with authentication."""
    user_id = "test-user-1"
    auth_override(user_id)

    test_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
                },
                "properties": {},
            }
        ],
    }

    # Create a mock AIMessage object
    mock_response = AsyncMock()
    mock_response.content = "Equatorial Coast"

    with domain_allowlist("wri.org"):  # Allow wri.org domain
        with patch("src.api.app.SMALL_MODEL") as mock_model:
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            response = await client.post(
                "/api/custom_area_name",
                json=test_geojson,
                headers={"Authorization": "Bearer test-token"},
            )

    assert response.status_code == 200
    data = response.json()
    assert "name" in data
    assert data["name"] == "Equatorial Coast"


@pytest.mark.asyncio
async def test_custom_area_name_invalid_geojson(client, auth_override):
    """Test area naming with invalid GeoJSON structure."""
    user_id = "test-user-1"
    auth_override(user_id)

    invalid_geojson = {
        "type": "Feature",  # Should be FeatureCollection
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
        },
        "properties": {},
    }

    with domain_allowlist("wri.org"):  # Allow wri.org domain
        response = await client.post(
            "/api/custom_area_name",
            json=invalid_geojson,
            headers={"Authorization": "Bearer test-token"},
        )

    # The endpoint expects FeatureCollection, so this should fail validation
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_custom_area_name_with_realistic_geometry(client, auth_override):
    """Test area naming with a more realistic geographic area."""
    user_id = "test-user-1"
    auth_override(user_id)

    # A more realistic polygon representing a small area (e.g., a city block)
    test_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-74.0059, 40.7128],  # NYC coordinates
                            [-74.0059, 40.7138],
                            [-74.0049, 40.7138],
                            [-74.0049, 40.7128],
                            [-74.0059, 40.7128],
                        ]
                    ],
                },
                "properties": {},
            }
        ],
    }

    # Create a mock AIMessage object
    mock_response = AsyncMock()
    mock_response.content = "Equatorial Coast"

    with domain_allowlist("wri.org"):  # Allow wri.org domain
        with patch("src.api.app.SMALL_MODEL") as mock_model:
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            response = await client.post(
                "/api/custom_area_name",
                json=test_geojson,
                headers={"Authorization": "Bearer test-token"},
            )

    assert response.status_code == 200
    data = response.json()
    assert "name" in data
    assert data["name"] == "Equatorial Coast"
