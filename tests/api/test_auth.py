"""Tests for authentication-related endpoints."""
import os
import pytest
from unittest.mock import patch
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import FastAPI
from contextlib import contextmanager

# Import the API app directly from the src package
from src.api import app as api

@contextmanager
def domain_allowlist(domains: str):
    """Context manager to set and reset DOMAINS_ALLOWLIST."""
    domain_list = domains.split(",")
    original = os.environ.get("DOMAINS_ALLOWLIST")
    os.environ["DOMAINS_ALLOWLIST"] = ",".join(domain_list)
    try:
        with patch.object(api, "DOMAINS_ALLOWLIST", domain_list):
            yield domain_list
    finally:
        if original is not None:
            os.environ["DOMAINS_ALLOWLIST"] = original
        else:
            del os.environ["DOMAINS_ALLOWLIST"]

# Mock user responses for different scenarios
MOCK_AUTHORIZED_USER = {
    "id": "test-user-1",
    "name": "Test User",
    "email": "test@developmentseed.org",
    "createdAt": "2024-01-01T00:00:00",
    "updatedAt": "2024-01-01T00:00:00"
}

MOCK_ALTERNATE_DOMAIN_USER = {
    "id": "test-user-2",
    "name": "WRI User",
    "email": "test@wri.org",
    "createdAt": "2024-01-01T00:00:00",
    "updatedAt": "2024-01-01T00:00:00"
}

MOCK_UNAUTHORIZED_USER = {
    "id": "test-user-3",
    "name": "Unauthorized User",
    "email": "test@unauthorized.com",
    "createdAt": "2024-01-01T00:00:00",
    "updatedAt": "2024-01-01T00:00:00"
}

def mock_rw_api_response(user_data):
    """Helper to create a mock response object."""
    class MockResponse:
        def __init__(self, json_data, status_code):
            self.json_data = json_data
            self.status_code = status_code
            self.text = str(json_data)

        def json(self):
            return self.json_data

    return MockResponse(user_data, 200)

@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the user info cache before each test."""
    api._user_info_cache.clear()

@pytest.mark.parametrize("user_data,expected_status,expected_error", [
    (MOCK_AUTHORIZED_USER, 200, None),  # developmentseed.org user should succeed
    (MOCK_ALTERNATE_DOMAIN_USER, 200, None),  # wri.org user should succeed
    (MOCK_UNAUTHORIZED_USER, 403, "User not allowed to access this API"),  # unauthorized domain should fail
])
@pytest.mark.asyncio
async def test_email_domain_authorization(user_data, expected_status, expected_error, db_session: AsyncSession):
    """Test that only users with allowed email domains can access the API."""
    with domain_allowlist("developmentseed.org,wri.org"):
        with patch('requests.get') as mock_get:
            # Mock the RW API response
            mock_response = mock_rw_api_response(user_data)
            mock_get.return_value = mock_response
            
            # Test the auth endpoint using async client
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://test") as client:
                response = await client.get(
                    "/api/auth/me",
                    headers={"Authorization": "Bearer test-token"}
                )
        
        assert response.status_code == expected_status
        
        if expected_error:
            assert expected_error in response.json()["detail"]
        else:
            # For successful requests, verify the user data is returned correctly
            user_response = response.json()
            assert user_response["id"] == user_data["id"]
            assert user_response["email"] == user_data["email"]
            assert user_response["name"] == user_data["name"]

@pytest.mark.asyncio
async def test_missing_bearer_token(db_session: AsyncSession):
    """Test that requests without a Bearer token are rejected."""
    with domain_allowlist("developmentseed.org,wri.org"):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://test") as client:
            response = await client.get(
                "/api/auth/me",
                headers={"Authorization": "test-token"}  # Missing "Bearer" prefix
            )
        assert response.status_code == 401
        assert "Missing Bearer token" in response.json()["detail"]


@pytest.mark.asyncio
async def test_missing_authorization_header(db_session: AsyncSession):
    """Test that requests without an Authorization header are rejected."""
    os.environ["DOMAINS_ALLOWLIST"] = "developmentseed.org,wri.org"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://test") as client:
        response = await client.get("/api/auth/me")  # No Authorization header
    assert response.status_code == 422  # FastAPI validation error
