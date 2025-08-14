"""Tests for /api/chat endpoint quota response headers."""

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


class TestChatQuotaHeaders:
    """Test /api/chat endpoint quota response headers functionality."""

    @pytest.mark.asyncio
    async def test_chat_includes_quota_headers_when_enabled(self, client):
        """Test that /api/chat includes quota headers when quota checking is enabled."""
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
                
                # Should have quota headers
                assert "X-Prompts-Used" in response.headers
                assert "X-Prompts-Quota" in response.headers
                assert response.headers["X-Prompts-Used"] == "1"
                assert response.headers["X-Prompts-Quota"] == str(APISettings.regular_user_daily_quota)

    @pytest.mark.asyncio
    async def test_chat_excludes_quota_headers_when_disabled(self, client):
        """Test that /api/chat excludes quota headers when quota checking is disabled."""
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
                    
                    # Should NOT have quota headers
                    assert "X-Prompts-Used" not in response.headers
                    assert "X-Prompts-Quota" not in response.headers

        finally:
            APISettings.enable_quota_checking = original_setting

    @pytest.mark.asyncio
    async def test_chat_quota_headers_increment_with_multiple_calls(self, client):
        """Test that quota headers increment with multiple /api/chat calls."""
        with patch("requests.get") as mock_get:
            mock_response = mock_rw_api_response("Test User")
            mock_get.return_value = mock_response

            with patch("src.api.app.stream_chat") as mock_stream:
                mock_stream.return_value = iter([b'{"response": "Hello!"}\\n'])

                # First call
                response1 = await client.post(
                    "/api/chat",
                    json={"query": "First message", "thread_id": "test-thread-123"},
                    headers={"Authorization": "Bearer test-token"}
                )
                assert response1.status_code == 200
                assert response1.headers["X-Prompts-Used"] == "1"

                # Second call
                response2 = await client.post(
                    "/api/chat", 
                    json={"query": "Second message", "thread_id": "test-thread-123"},
                    headers={"Authorization": "Bearer test-token"}
                )
                assert response2.status_code == 200
                assert response2.headers["X-Prompts-Used"] == "2"

    @pytest.mark.asyncio
    async def test_chat_anonymous_user_has_quota_headers(self, anonymous_client):
        """Test that anonymous users get quota headers with anonymous quota limits."""
        with patch("src.api.app.stream_chat") as mock_stream:
            mock_stream.return_value = iter([b'{"response": "Hello!"}\\n'])

            response = await anonymous_client.post(
                "/api/chat",
                json={"query": "Test message", "thread_id": "test-thread-123"}
            )

            assert response.status_code == 200
            
            # Should have quota headers with anonymous limits
            assert "X-Prompts-Used" in response.headers
            assert "X-Prompts-Quota" in response.headers
            assert response.headers["X-Prompts-Used"] == "1"
            assert response.headers["X-Prompts-Quota"] == str(APISettings.anonymous_user_daily_quota)

    @pytest.mark.asyncio
    async def test_chat_admin_user_has_higher_quota_headers(self, client):
        """Test that admin users get higher quota limits in headers."""
        with patch("requests.get") as mock_get:
            # Create admin user mock response
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

            with patch("src.api.app.stream_chat") as mock_stream:
                mock_stream.return_value = iter([b'{"response": "Hello!"}\\n'])

                response = await client.post(
                    "/api/chat",
                    json={"query": "Test message", "thread_id": "test-thread-123"},
                    headers={"Authorization": "Bearer test-token"}
                )

                assert response.status_code == 200
                assert response.headers["X-Prompts-Quota"] == str(APISettings.admin_user_daily_quota)
                assert response.headers["X-Prompts-Used"] == "1"

    @pytest.mark.asyncio
    async def test_chat_quota_headers_consistency_with_auth_me(self, client):
        """Test that quota headers in /api/chat are consistent with /auth/me response."""
        with patch("requests.get") as mock_get:
            mock_response = mock_rw_api_response("Test User")
            mock_get.return_value = mock_response

            # Make a chat call first
            with patch("src.api.app.stream_chat") as mock_stream:
                mock_stream.return_value = iter([b'{"response": "Hello!"}\\n'])

                chat_response = await client.post(
                    "/api/chat",
                    json={"query": "Test message", "thread_id": "test-thread-123"},
                    headers={"Authorization": "Bearer test-token"}
                )
                
                assert chat_response.status_code == 200
                chat_used = chat_response.headers["X-Prompts-Used"]
                chat_quota = chat_response.headers["X-Prompts-Quota"]

            # Now check /auth/me
            auth_response = await client.get(
                "/api/auth/me", 
                headers={"Authorization": "Bearer test-token"}
            )
            
            assert auth_response.status_code == 200
            auth_data = auth_response.json()
            
            # Values should be consistent (auth/me increments by 1 more)
            assert str(auth_data["promptsUsed"]) == "2"  # chat call + auth/me call
            assert str(auth_data["promptQuota"]) == chat_quota

    @pytest.mark.asyncio
    async def test_chat_returns_429_when_quota_exceeded(self, client):
        """Test that /api/chat returns 429 when quota is exceeded."""
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
                    assert "Daily free limit" in response2.json()["detail"]

        finally:
            APISettings.regular_user_daily_quota = original_quota

    def test_anonymous_client_fixture_exists(self, anonymous_client):
        """Test that the anonymous_client fixture is properly available."""
        # This test verifies the fixture is working correctly
        assert anonymous_client is not None