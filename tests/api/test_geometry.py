"""Tests for the geometry lookup endpoint."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_geometry_requires_auth(client):
    """Geometry endpoint requires authentication."""
    response = await client.get("/api/geometry/gadm/IND.1_1")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_geometry_not_found(client, auth_override):
    """Returns 404 when geometry is not found for source/id."""
    auth_override("test-user-1")

    with patch(
        "src.api.routers.geometry.get_geometry_data", new_callable=AsyncMock
    ) as mock_get:
        mock_get.return_value = None

        response = await client.get(
            "/api/geometry/gadm/DOES_NOT_EXIST",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 404
    assert "Geometry not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_geometry_invalid_source(client, auth_override):
    """Returns 400 when source type is invalid."""
    auth_override("test-user-1")

    with patch(
        "src.api.routers.geometry.get_geometry_data", new_callable=AsyncMock
    ) as mock_get:
        mock_get.side_effect = ValueError("Unknown source: invalid_source")

        response = await client.get(
            "/api/geometry/invalid_source/123",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_geometry_success(client, auth_override):
    """Returns geometry data for a valid source and ID."""
    auth_override("test-user-1")

    mock_result = {
        "name": "Andhra Pradesh",
        "subtype": "gadm1",
        "source": "gadm",
        "src_id": "IND.2_1",
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [[80, 14], [80, 15], [81, 15], [81, 14], [80, 14]]
            ],
        },
    }

    with patch(
        "src.api.routers.geometry.get_geometry_data", new_callable=AsyncMock
    ) as mock_get:
        mock_get.return_value = mock_result

        response = await client.get(
            "/api/geometry/gadm/IND.2_1",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Andhra Pradesh"
    assert data["source"] == "gadm"
    assert data["src_id"] == "IND.2_1"
    assert "geometry" in data
