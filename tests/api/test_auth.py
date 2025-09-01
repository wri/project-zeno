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
        with patch("httpx.AsyncClient") as mock_client_class:
            # Mock the AsyncClient context manager and get method
            mock_client = (
                mock_client_class.return_value.__aenter__.return_value
            )
            mock_client.get.return_value = mock_rw_api_response(username)

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
        with patch("httpx.AsyncClient") as mock_client_class:
            # Mock the AsyncClient context manager and get method
            mock_client = (
                mock_client_class.return_value.__aenter__.return_value
            )
            mock_client.get.return_value = mock_rw_api_response(
                "Unauthorized User"
            )

            # Test the auth endpoint
            response = await client.get(
                "/api/auth/me?domains_allowlist=unauthorized.com",
                headers={"Authorization": "Bearer test-token"},
            )

        assert response.status_code == 403
        assert (
            "User not allowed to access this API" in response.json()["detail"]
        )


@pytest.mark.asyncio
async def test_email_whitelist_allows_access(client):
    """Test that users on email whitelist can access even if domain not allowed."""
    from src.api.data_models import WhitelistedUserOrm
    from tests.conftest import async_session_maker

    # Add test email to whitelist
    async with async_session_maker() as session:
        whitelisted_user = WhitelistedUserOrm(email="test@gmail.com")
        session.add(whitelisted_user)
        await session.commit()

    with domain_allowlist(
        "developmentseed.org,wri.org"
    ):  # gmail.com not in domain list
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = (
                mock_client_class.return_value.__aenter__.return_value
            )
            # Mock user with gmail.com email (not in domain allowlist but in email whitelist)
            mock_response = mock_rw_api_response("Gmail User")
            mock_response.json_data["email"] = "test@gmail.com"
            mock_client.get.return_value = mock_response

            response = await client.get(
                "/api/auth/me", headers={"Authorization": "Bearer test-token"}
            )

        assert response.status_code == 200
        user_data = response.json()
        assert user_data["email"] == "test@gmail.com"


@pytest.mark.asyncio
async def test_email_whitelist_case_insensitive(client):
    """Test that email whitelist matching is case insensitive."""
    from src.api.data_models import WhitelistedUserOrm
    from tests.conftest import async_session_maker

    # Add lowercase email to whitelist
    async with async_session_maker() as session:
        whitelisted_user = WhitelistedUserOrm(email="casetest@example.com")
        session.add(whitelisted_user)
        await session.commit()

    with domain_allowlist(
        "developmentseed.org"
    ):  # example.com not in domain list
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = (
                mock_client_class.return_value.__aenter__.return_value
            )
            # Mock user with uppercase email - create fresh mock
            mock_response = mock_rw_api_response("Gmail User")
            mock_response.json_data = {
                "id": "test-user-casetest",
                "name": "Case Test User",
                "email": "CASETEST@EXAMPLE.COM",
                "createdAt": "2024-01-01T00:00:00Z",
                "updatedAt": "2024-01-01T00:00:00Z",
            }
            mock_client.get.return_value = mock_response

            response = await client.get(
                "/api/auth/me", headers={"Authorization": "Bearer test-token"}
            )

        assert response.status_code == 200


@pytest.mark.asyncio
async def test_domain_whitelist_still_works_with_email_feature(client):
    """Test that existing domain whitelist functionality is preserved."""
    # Clear cache to ensure clean state
    api._user_info_cache.clear()

    with domain_allowlist("developmentseed.org,wri.org"):
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = (
                mock_client_class.return_value.__aenter__.return_value
            )
            mock_client.get.return_value = mock_rw_api_response("Test User")

            response = await client.get(
                "/api/auth/me", headers={"Authorization": "Bearer test-token"}
            )

        assert response.status_code == 200
        user_data = response.json()
        assert user_data["name"] == "Test User"


@pytest.mark.asyncio
async def test_user_blocked_when_not_in_domain_or_email_whitelist(client):
    """Test that users are blocked when not in either domain or email whitelist."""
    with domain_allowlist("developmentseed.org,wri.org"):
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = (
                mock_client_class.return_value.__aenter__.return_value
            )
            # Mock user with unauthorized domain and not in email whitelist
            mock_response = mock_rw_api_response("Unauthorized User")
            mock_response.json_data["email"] = "test@blocked.com"
            mock_client.get.return_value = mock_response

            response = await client.get(
                "/api/auth/me", headers={"Authorization": "Bearer test-token"}
            )

        assert response.status_code == 403
        assert (
            "User not allowed to access this API" in response.json()["detail"]
        )
