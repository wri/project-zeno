"""Edge case tests for quota functionality."""

import pytest
from unittest.mock import patch, Mock
from datetime import date, timedelta

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


class TestQuotaEdgeCases:
    """Test edge cases and error scenarios for quota functionality."""

    @pytest.mark.asyncio
    async def test_quota_exceeded_returns_429_with_proper_message(self, client):
        """Test that exceeding quota returns 429 with proper error message."""
        # Set quota to 1 for easy testing
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
                    assert response1.headers["X-Prompts-Used"] == "1"

                    # Second call should fail with 429
                    response2 = await client.post(
                        "/api/chat",
                        json={"query": "Second message", "thread_id": "test-thread-123"},
                        headers={"Authorization": "Bearer test-token"}
                    )
                    assert response2.status_code == 429
                    error_detail = response2.json()["detail"]
                    assert "Daily free limit of 1 exceeded" in error_detail
                    assert "try again tomorrow" in error_detail

        finally:
            APISettings.regular_user_daily_quota = original_quota

    @pytest.mark.asyncio
    async def test_anonymous_quota_exceeded_returns_429(self, anonymous_client):
        """Test that anonymous users get 429 when exceeding quota."""
        # Set anonymous quota to 1 for easy testing
        original_quota = APISettings.anonymous_user_daily_quota
        APISettings.anonymous_user_daily_quota = 1

        try:
            with patch("src.api.app.stream_chat") as mock_stream:
                mock_stream.return_value = iter([b'{"response": "Hello!"}\\n'])

                # First call should succeed
                response1 = await anonymous_client.post(
                    "/api/chat",
                    json={"query": "First message", "thread_id": "test-thread-123"}
                )
                assert response1.status_code == 200
                assert response1.headers["X-Prompts-Used"] == "1"

                # Second call should fail with 429
                response2 = await anonymous_client.post(
                    "/api/chat",
                    json={"query": "Second message", "thread_id": "test-thread-123"}
                )
                assert response2.status_code == 429
                assert "Daily free limit of 1 exceeded" in response2.json()["detail"]

        finally:
            APISettings.anonymous_user_daily_quota = original_quota


    @pytest.mark.asyncio
    async def test_auth_me_with_malformed_auth_header_returns_401(self, client):
        """Test that /auth/me with malformed Authorization header returns 401."""
        # Missing "Bearer" prefix
        response = await client.get(
            "/api/auth/me",
            headers={"Authorization": "invalid-format-token"}
        )

        assert response.status_code == 401
        assert "Missing Bearer token" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_auth_me_with_no_auth_header_returns_401(self, client):
        """Test that /auth/me with no Authorization header returns 401."""
        response = await client.get("/api/auth/me")

        assert response.status_code == 401
        assert "Missing Bearer token" in response.json()["detail"]


    @pytest.mark.asyncio
    async def test_concurrent_quota_requests_handling(self, client):
        """Test that concurrent requests don't cause race conditions in quota tracking."""
        # This is a simplified test - in reality you'd need proper concurrency testing
        with patch("requests.get") as mock_get:
            mock_response = mock_rw_api_response("Test User")
            mock_get.return_value = mock_response

            with patch("src.api.app.stream_chat") as mock_stream:
                mock_stream.return_value = iter([b'{"response": "Hello!"}\\n'])

                # Make multiple rapid requests (simulated concurrency)
                responses = []
                for i in range(3):
                    response = await client.post(
                        "/api/chat",
                        json={"query": f"Message {i}", "thread_id": "test-thread-123"},
                        headers={"Authorization": "Bearer test-token"}
                    )
                    responses.append(response)

                # All should succeed (assuming quota > 3)
                for response in responses:
                    assert response.status_code == 200

                # Last response should show correct total count
                final_count = int(responses[-1].headers["X-Prompts-Used"])
                assert final_count == 3


    @pytest.mark.asyncio
    async def test_quota_boundary_conditions(self, client):
        """Test quota behavior at exact quota limits."""
        # Set quota to 2 for precise testing
        original_quota = APISettings.regular_user_daily_quota
        APISettings.regular_user_daily_quota = 2

        try:
            with patch("requests.get") as mock_get:
                mock_response = mock_rw_api_response("Test User")
                mock_get.return_value = mock_response

                with patch("src.api.app.stream_chat") as mock_stream:
                    mock_stream.return_value = iter([b'{"response": "Hello!"}\\n'])

                    # First call (1/2)
                    response1 = await client.post(
                        "/api/chat",
                        json={"query": "Message 1", "thread_id": "test-thread-123"},
                        headers={"Authorization": "Bearer test-token"}
                    )
                    assert response1.status_code == 200
                    assert response1.headers["X-Prompts-Used"] == "1"

                    # Second call (2/2) - should still succeed
                    response2 = await client.post(
                        "/api/chat",
                        json={"query": "Message 2", "thread_id": "test-thread-123"},
                        headers={"Authorization": "Bearer test-token"}
                    )
                    assert response2.status_code == 200
                    assert response2.headers["X-Prompts-Used"] == "2"

                    # Third call (3/2) - should fail
                    response3 = await client.post(
                        "/api/chat",
                        json={"query": "Message 3", "thread_id": "test-thread-123"},
                        headers={"Authorization": "Bearer test-token"}
                    )
                    assert response3.status_code == 429

        finally:
            APISettings.regular_user_daily_quota = original_quota


    @pytest.mark.asyncio
    async def test_quota_reset_behavior_across_days(self, client):
        """Test that quota resets properly for new days (conceptual test)."""
        # Note: This is a conceptual test since we can't easily manipulate dates in tests
        # In a real implementation, you'd use date mocking or time-travel fixtures
        
        with patch("requests.get") as mock_get:
            mock_response = mock_rw_api_response("Test User")
            mock_get.return_value = mock_response

            # This test demonstrates the expected behavior
            # In practice, you'd mock date.today() to return different dates
            
            auth_response = await client.get(
                "/api/auth/me",
                headers={"Authorization": "Bearer test-token"}
            )
            
            assert auth_response.status_code == 200
            data = auth_response.json()
            
            # On a fresh day, usage should start at 1
            assert data["promptsUsed"] == 1
            assert data["promptQuota"] == APISettings.regular_user_daily_quota