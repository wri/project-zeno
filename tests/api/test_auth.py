"""Tests for authentication-related endpoints."""

from unittest.mock import patch

import pytest

from src.api.auth.dependencies import _user_info_cache
from tests.api.mock import mock_rw_api_response


@pytest.fixture(autouse=True)
def clear_cache():
    _user_info_cache.clear()


@pytest.mark.asyncio
async def test_auth_me_requires_bearer_token(client):
    response = await client.get("/api/auth/me")
    assert response.status_code == 401
    assert "Missing Bearer token" in response.json()["detail"]


@pytest.mark.asyncio
async def test_auth_me_returns_user_with_valid_token(client):
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = mock_client_class.return_value.__aenter__.return_value
        mock_client.get.return_value = mock_rw_api_response("Test User")

        response = await client.get(
            "/api/auth/me", headers={"Authorization": "Bearer test-token"}
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "Test User"
    assert payload["email"] == "test@developmentseed.org"


@pytest.mark.asyncio
async def test_auth_me_creates_user_without_whitelist_gates(client):
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = mock_client_class.return_value.__aenter__.return_value
        mock_response = mock_rw_api_response("Public User")
        mock_response.json_data["id"] = "public-user-1"
        mock_response.json_data["email"] = "public@example.org"
        mock_client.get.return_value = mock_response

        response = await client.get(
            "/api/auth/me", headers={"Authorization": "Bearer test-token"}
        )

    assert response.status_code == 200
    assert response.json()["id"] == "public-user-1"
