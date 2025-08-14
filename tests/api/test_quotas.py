"""Comprehensive tests for quota functionality."""

import pytest
from unittest.mock import patch

from src.utils.config import APISettings
from .mock import mock_rw_api_response


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the user info cache before each test."""
    from src.api import app as api
    api._user_info_cache.clear()


@pytest.fixture
def anonymous_client(client):
    """Client without authentication headers."""
    return client


class TestQuotaFunctionality:
    """Test core quota functionality across endpoints."""

    @pytest.mark.asyncio
    async def test_auth_me_includes_quota_info_when_enabled(self, client):
        """Test that /auth/me includes quota information when enabled."""
        with patch("requests.get") as mock_get:
            mock_response = mock_rw_api_response("Test User")
            mock_get.return_value = mock_response

            response = await client.get(
                "/api/auth/me", headers={"Authorization": "Bearer test-token"}
            )

            assert response.status_code == 200
            data = response.json()
            assert "promptsUsed" in data
            assert "promptQuota" in data
            assert data["promptsUsed"] == 1
            assert data["promptQuota"] == APISettings.regular_user_daily_quota

    @pytest.mark.asyncio
    async def test_auth_me_quota_disabled_returns_null(self, client):
        """Test that /auth/me returns null quota values when disabled."""
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
                assert data["promptsUsed"] is None
                assert data["promptQuota"] is None

        finally:
            APISettings.enable_quota_checking = original_setting

    @pytest.mark.asyncio
    async def test_quota_increments_correctly(self, client):
        """Test that quota usage increments with multiple calls."""
        with patch("requests.get") as mock_get:
            mock_response = mock_rw_api_response("Test User")
            mock_get.return_value = mock_response

            # First call
            response1 = await client.get(
                "/api/auth/me", headers={"Authorization": "Bearer test-token"}
            )
            assert response1.status_code == 200
            assert response1.json()["promptsUsed"] == 1

            # Second call
            response2 = await client.get(
                "/api/auth/me", headers={"Authorization": "Bearer test-token"}
            )
            assert response2.status_code == 200
            assert response2.json()["promptsUsed"] == 2

    @pytest.mark.asyncio
    async def test_chat_includes_quota_headers_when_enabled(self, client):
        """Test that /api/chat includes quota headers when enabled."""
        with patch("requests.get") as mock_get:
            mock_response = mock_rw_api_response("Test User")
            mock_get.return_value = mock_response

            with patch("src.api.app.stream_chat") as mock_stream:
                mock_stream.return_value = iter([b'{"response": "Hello!"}\\n'])

                response = await client.post(
                    "/api/chat",
                    json={"query": "Test message", "thread_id": "test-thread-123"},
                    headers={"Authorization": "Bearer test-token"}
                )

                assert response.status_code == 200
                assert "X-Prompts-Used" in response.headers
                assert "X-Prompts-Quota" in response.headers
                assert response.headers["X-Prompts-Used"] == "1"
                assert response.headers["X-Prompts-Quota"] == str(APISettings.regular_user_daily_quota)

    @pytest.mark.asyncio
    async def test_chat_excludes_quota_headers_when_disabled(self, client):
        """Test that /api/chat excludes quota headers when disabled."""
        original_setting = APISettings.enable_quota_checking
        APISettings.enable_quota_checking = False

        try:
            with patch("requests.get") as mock_get:
                mock_response = mock_rw_api_response("Test User")
                mock_get.return_value = mock_response

                with patch("src.api.app.stream_chat") as mock_stream:
                    mock_stream.return_value = iter([b'{"response": "Hello!"}\\n'])

                    response = await client.post(
                        "/api/chat",
                        json={"query": "Test message", "thread_id": "test-thread-123"},
                        headers={"Authorization": "Bearer test-token"}
                    )

                    assert response.status_code == 200
                    assert "X-Prompts-Used" not in response.headers
                    assert "X-Prompts-Quota" not in response.headers

        finally:
            APISettings.enable_quota_checking = original_setting

    @pytest.mark.asyncio
    async def test_admin_user_has_higher_quota(self, client):
        """Test that admin users get higher quota limits."""
        with patch("requests.get") as mock_get:
            admin_user_data = {
                "id": "test-admin-1",
                "name": "Admin User",
                "email": "admin@wri.org",
                "createdAt": "2024-01-01T00:00:00Z",
                "updatedAt": "2024-01-01T00:00:00Z",
                "userType": "admin"
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

    @pytest.mark.asyncio
    async def test_anonymous_user_quota_tracking(self, anonymous_client):
        """Test that anonymous users get proper quota tracking."""
        with patch("src.api.app.stream_chat") as mock_stream:
            mock_stream.return_value = iter([b'{"response": "Hello!"}\\n'])

            response = await anonymous_client.post(
                "/api/chat",
                json={"query": "Test message", "thread_id": "test-thread-123"}
            )

            assert response.status_code == 200
            assert "X-Prompts-Used" in response.headers
            assert "X-Prompts-Quota" in response.headers
            assert response.headers["X-Prompts-Used"] == "1"
            assert response.headers["X-Prompts-Quota"] == str(APISettings.anonymous_user_daily_quota)

    @pytest.mark.asyncio
    async def test_quota_consistency_across_endpoints(self, client):
        """Test that quota state is consistent between /auth/me and /api/chat."""
        with patch("requests.get") as mock_get:
            mock_response = mock_rw_api_response("Test User")
            mock_get.return_value = mock_response

            # Make /auth/me call first
            auth_response = await client.get(
                "/api/auth/me", headers={"Authorization": "Bearer test-token"}
            )
            assert auth_response.status_code == 200
            auth_used = auth_response.json()["promptsUsed"]

            # Make chat call
            with patch("src.api.app.stream_chat") as mock_stream:
                mock_stream.return_value = iter([b'{"response": "Hello!"}\\n'])

                chat_response = await client.post(
                    "/api/chat",
                    json={"query": "Test message", "thread_id": "test-thread-123"},
                    headers={"Authorization": "Bearer test-token"}
                )
                
                assert chat_response.status_code == 200
                chat_used = int(chat_response.headers["X-Prompts-Used"])
                chat_quota = int(chat_response.headers["X-Prompts-Quota"])

            # Values should be consistent and incremental
            assert chat_used == auth_used + 1  # auth(1) -> chat(2)
            assert chat_quota == APISettings.regular_user_daily_quota

    @pytest.mark.asyncio
    async def test_quota_exceeded_returns_429(self, client):
        """Test that exceeding quota returns 429 status."""
        # Set very low quota for testing
        original_quota = APISettings.regular_user_daily_quota
        APISettings.regular_user_daily_quota = 1

        try:
            with patch("requests.get") as mock_get:
                mock_response = mock_rw_api_response("Test User")
                mock_get.return_value = mock_response

                with patch("src.api.app.stream_chat") as mock_stream:
                    mock_stream.return_value = iter([b'{"response": "Hello!"}\\n'])

                    # First call should succeed
                    response1 = await client.post(
                        "/api/chat",
                        json={"query": "First message", "thread_id": "test-thread-123"},
                        headers={"Authorization": "Bearer test-token"}
                    )
                    assert response1.status_code == 200

                    # Second call should fail with 429
                    response2 = await client.post(
                        "/api/chat",
                        json={"query": "Second message", "thread_id": "test-thread-123"},
                        headers={"Authorization": "Bearer test-token"}
                    )
                    assert response2.status_code == 429
                    assert "Daily free limit of 1 exceeded" in response2.json()["detail"]

        finally:
            APISettings.regular_user_daily_quota = original_quota