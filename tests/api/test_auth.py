"""Tests for authentication-related endpoints."""

import os
from contextlib import contextmanager
from unittest.mock import patch

import pytest

# Import the API app directly from the src package
from src.api import app as api

from .mock import mock_rw_api_response


@contextmanager
def domain_allowlist(domains: str):
    """Context manager to set and reset DOMAINS_ALLOWLIST."""
    domain_list = domains.split(",")
    try:
        with patch.object(api.APISettings, "domains_allowlist_str", domains):
            yield domain_list
    finally:
        pass


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the user info cache before each test."""
    api._user_info_cache.clear()


@pytest.mark.parametrize(
    "username,expected_status,expected_error",
    [
        ("Test User", 200, None),  # developmentseed.org user should succeed
        ("WRI User", 200, None),  # wri.org user should succeed
        (
            "Unauthorized User",
            403,
            "User not allowed to access this API",
        ),  # unauthorized domain should fail
    ],
)
@pytest.mark.asyncio
async def test_email_domain_authorization(
    username, expected_status, expected_error, client
):
    """Test that only users with allowed email domains can access the API."""
    with domain_allowlist("developmentseed.org,wri.org"):
        with patch("requests.get") as mock_get:
            # Mock the RW API response
            mock_response = mock_rw_api_response(username)
            mock_get.return_value = mock_response

            # Test the auth endpoint
            response = await client.get(
                "/api/auth/me", headers={"Authorization": "Bearer test-token"}
            )

        assert response.status_code == expected_status

        if expected_error:
            assert expected_error in response.json()["detail"]
        else:
            # For successful requests, verify the user data is returned correctly
            user_response = response.json()
            assert user_response["name"] == username


@pytest.mark.asyncio
async def test_missing_bearer_token(client):
    """Test that requests without a Bearer token are rejected."""
    with domain_allowlist("developmentseed.org,wri.org"):
        response = await client.get(
            "/api/auth/me",
            headers={"Authorization": "test-token"},  # Missing "Bearer" prefix
        )
        assert response.status_code == 401
        assert (
            "Missing Bearer token in Authorization header"
            in response.json()["detail"]
        )


@pytest.mark.asyncio
async def test_missing_authorization_header(client):
    """Test that requests without an Authorization header are rejected."""
    os.environ["DOMAINS_ALLOWLIST"] = "developmentseed.org,wri.org"
    response = await client.get("/api/auth/me")  # No Authorization header
    assert response.status_code == 401
    assert (
        "Missing Bearer token in Authorization header"
        in response.json()["detail"]
    )


@pytest.mark.asyncio
async def test_user_cant_override_email_domain_authorization(client):
    """Test that only users cant override email domain authorization through query params."""
    with domain_allowlist("developmentseed.org,wri.org"):
        with patch("requests.get") as mock_get:
            # Mock the RW API response
            mock_response = mock_rw_api_response("Unauthorized User")
            mock_get.return_value = mock_response

            # Test the auth endpoint
            response = await client.get(
                "/api/auth/me?domains_allowlist=unauthorized.com",
                headers={"Authorization": "Bearer test-token"},
            )

        assert response.status_code == 403
        assert (
            "User not allowed to access this API" in response.json()["detail"]
        )
