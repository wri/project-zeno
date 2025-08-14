"""Tests for /auth/me endpoint quota response keys."""

import pytest
from unittest.mock import patch

from src.api.data_models import UserType
from src.utils.config import APISettings
from .mock import mock_rw_api_response


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the user info cache before each test."""
    from src.api import app as api
    api._user_info_cache.clear()


class TestAuthMeQuotaKeys:
    """Test /auth/me endpoint quota response keys functionality."""

    @pytest.mark.asyncio
    async def test_auth_me_includes_quota_keys_when_enabled(self, client):
        """Test that /auth/me includes quota keys when quota checking is enabled."""
        with patch("requests.get") as mock_get:
            # Mock regular user response
            mock_response = mock_rw_api_response("Test User")
            mock_get.return_value = mock_response

            response = await client.get(
                "/api/auth/me", headers={"Authorization": "Bearer test-token"}
            )

            assert response.status_code == 200
            data = response.json()
            
            # Should have quota keys
            assert "promptsUsed" in data
            assert "promptQuota" in data
            assert data["promptsUsed"] == 1  # First call increments to 1
            assert data["promptQuota"] == APISettings.regular_user_daily_quota

    @pytest.mark.asyncio
    async def test_auth_me_excludes_quota_keys_when_disabled(self, client):
        """Test that /auth/me excludes quota keys when quota checking is disabled."""
        original_setting = APISettings.enable_quota_checking
        APISettings.enable_quota_checking = False

        try:
            with patch("requests.get") as mock_get:
                mock_response = mock_rw_api_response("Test User")
                mock_get.return_value = mock_response

                response = await client.get(
                    "/api/auth/me", headers={"Authorization": "Bearer test-token"}
                )

                assert response.status_code == 200
                data = response.json()
                
                # Should have quota keys but set to null when disabled
                assert "promptsUsed" in data
                assert "promptQuota" in data
                assert data["promptsUsed"] is None
                assert data["promptQuota"] is None
                # Should have regular user fields
                assert "name" in data
                assert "email" in data
                assert data["name"] == "Test User"

        finally:
            APISettings.enable_quota_checking = original_setting

    @pytest.mark.asyncio
    async def test_auth_me_quota_increments_with_multiple_calls(self, client):
        """Test that quota usage increments with multiple /auth/me calls."""
        with patch("requests.get") as mock_get:
            mock_response = mock_rw_api_response("Test User")
            mock_get.return_value = mock_response

            # First call
            response1 = await client.get(
                "/api/auth/me", headers={"Authorization": "Bearer test-token"}
            )
            assert response1.status_code == 200
            data1 = response1.json()
            assert data1["promptsUsed"] == 1

            # Second call
            response2 = await client.get(
                "/api/auth/me", headers={"Authorization": "Bearer test-token"}
            )
            assert response2.status_code == 200
            data2 = response2.json()
            assert data2["promptsUsed"] == 2

    @pytest.mark.asyncio
    async def test_auth_me_admin_user_has_higher_quota(self, client):
        """Test that admin users get higher quota limits."""
        with patch("requests.get") as mock_get:
            # Create admin user mock response
            admin_user_data = {
                "id": "test-admin-1",
                "name": "Admin User", 
                "email": "admin@wri.org",
                "createdAt": "2024-01-01T00:00:00Z",
                "updatedAt": "2024-01-01T00:00:00Z",
                "userType": "admin"  # This makes them admin
            }
            
            class MockAdminResponse:
                def __init__(self):
                    self.status_code = 200
                    self.text = str(admin_user_data)

                def json(self):
                    return admin_user_data

            mock_get.return_value = MockAdminResponse()

            response = await client.get(
                "/api/auth/me", headers={"Authorization": "Bearer test-token"}
            )

            assert response.status_code == 200
            data = response.json()
            assert data["promptQuota"] == APISettings.admin_user_daily_quota
            assert data["promptsUsed"] == 1

    @pytest.mark.asyncio
    async def test_auth_me_regular_user_has_regular_quota(self, client):
        """Test that regular users get regular quota limits."""
        with patch("requests.get") as mock_get:
            mock_response = mock_rw_api_response("Test User")
            mock_get.return_value = mock_response

            response = await client.get(
                "/api/auth/me", headers={"Authorization": "Bearer test-token"}
            )

            assert response.status_code == 200
            data = response.json()
            assert data["promptQuota"] == APISettings.regular_user_daily_quota
            assert data["promptsUsed"] == 1

    @pytest.mark.asyncio
    async def test_auth_me_quota_fields_use_camel_case(self, client):
        """Test that quota fields are returned in camelCase format."""
        with patch("requests.get") as mock_get:
            mock_response = mock_rw_api_response("Test User")
            mock_get.return_value = mock_response

            response = await client.get(
                "/api/auth/me", headers={"Authorization": "Bearer test-token"}
            )

            assert response.status_code == 200
            data = response.json()
            
            # Check camelCase field names (due to alias_generator in schema)
            assert "promptsUsed" in data
            assert "promptQuota" in data
            # Should NOT have snake_case versions
            assert "prompts_used" not in data
            assert "prompt_quota" not in data

    @pytest.mark.asyncio
    async def test_auth_me_unauthorized_returns_401(self, client):
        """Test that /auth/me returns 401 for unauthorized requests."""
        response = await client.get("/api/auth/me")
        
        assert response.status_code == 401
        assert "Missing Bearer token" in response.json()["detail"]