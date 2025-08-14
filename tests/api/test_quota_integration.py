"""Integration tests for quota functionality across endpoints."""

import pytest
from unittest.mock import patch
from datetime import date

from src.api.data_models import DailyUsageOrm
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


class TestQuotaIntegration:
    """Test quota functionality integration across endpoints."""

    @pytest.mark.asyncio
    async def test_quota_consistency_across_endpoints(self, client):
        """Test that quota state is consistent between /api/chat and /auth/me."""
        with patch("requests.get") as mock_get:
            mock_response = mock_rw_api_response("Test User")
            mock_get.return_value = mock_response

            # Make initial /auth/me call
            auth_response1 = await client.get(
                "/api/auth/me",
                headers={"Authorization": "Bearer test-token"}
            )
            assert auth_response1.status_code == 200
            auth_data1 = auth_response1.json()
            initial_used = auth_data1["promptsUsed"]

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

            # Make another /auth/me call
            auth_response2 = await client.get(
                "/api/auth/me",
                headers={"Authorization": "Bearer test-token"}
            )
            assert auth_response2.status_code == 200
            auth_data2 = auth_response2.json()

            # Verify progression: initial(1) -> chat(2) -> auth/me(3)
            assert initial_used == 1
            assert chat_used == 2
            assert auth_data2["promptsUsed"] == 3
            assert auth_data2["promptQuota"] == chat_quota

    @pytest.mark.asyncio
    async def test_database_quota_tracking(self, client):
        """Test that quota usage is properly tracked in the database."""
        with patch("requests.get") as mock_get:
            mock_response = mock_rw_api_response("Test User")
            mock_get.return_value = mock_response

            # Get initial database state
            from tests.conftest import async_session_maker
            from sqlalchemy import select

            async with async_session_maker() as session:
                # Check if usage record exists initially
                stmt = select(DailyUsageOrm).filter_by(
                    id="user:test-user-1", 
                    date=date.today()
                )
                result = await session.execute(stmt)
                initial_record = result.scalars().first()
                
                # Should be None initially
                assert initial_record is None

            # Make API call to trigger quota tracking
            with patch("src.api.app.stream_chat") as mock_stream:
                mock_stream.return_value = iter([b'{"response": "Hello!"}\\n'])

                response = await client.post(
                    "/api/chat",
                    json={"query": "Test message", "thread_id": "test-thread-123"},
                    headers={"Authorization": "Bearer test-token"}
                )
                
                assert response.status_code == 200

            # Check database record was created
            async with async_session_maker() as session:
                stmt = select(DailyUsageOrm).filter_by(
                    id="user:test-user-1",
                    date=date.today()
                )
                result = await session.execute(stmt)
                usage_record = result.scalars().first()
                
                assert usage_record is not None
                assert usage_record.usage_count == 1
                assert usage_record.id == "user:test-user-1"
                assert usage_record.date == date.today()

    @pytest.mark.asyncio
    async def test_anonymous_user_quota_tracking(self, anonymous_client):
        """Test that anonymous users' quota is properly tracked."""
        # Make multiple calls as anonymous user
        with patch("src.api.app.stream_chat") as mock_stream:
            mock_stream.return_value = iter([b'{"response": "Hello!"}\\n'])

            # First call
            response1 = await anonymous_client.post(
                "/api/chat",
                json={"query": "First message", "thread_id": "test-thread-123"}
            )
            assert response1.status_code == 200
            assert response1.headers["X-Prompts-Used"] == "1"
            assert response1.headers["X-Prompts-Quota"] == str(APISettings.anonymous_user_daily_quota)

            # Second call
            response2 = await anonymous_client.post(
                "/api/chat",
                json={"query": "Second message", "thread_id": "test-thread-123"}
            )
            assert response2.status_code == 200
            assert response2.headers["X-Prompts-Used"] == "2"

    @pytest.mark.asyncio
    async def test_different_users_have_separate_quotas(self, client):
        """Test that different users have separate quota tracking."""
        # User 1
        with patch("requests.get") as mock_get:
            mock_response = mock_rw_api_response("Test User")
            mock_get.return_value = mock_response

            with patch("src.api.app.stream_chat") as mock_stream:
                mock_stream.return_value = iter([b'{"response": "Hello!"}\\n'])

                response1 = await client.post(
                    "/api/chat",
                    json={"query": "Test message", "thread_id": "test-thread-123"},
                    headers={"Authorization": "Bearer test-token-1"}
                )
                assert response1.status_code == 200
                assert response1.headers["X-Prompts-Used"] == "1"

        # User 2 (different user)
        with patch("requests.get") as mock_get:
            mock_response = mock_rw_api_response("WRI User")
            mock_get.return_value = mock_response

            with patch("src.api.app.stream_chat") as mock_stream:
                mock_stream.return_value = iter([b'{"response": "Hello!"}\\n'])

                response2 = await client.post(
                    "/api/chat",
                    json={"query": "Test message", "thread_id": "test-thread-456"},
                    headers={"Authorization": "Bearer test-token-2"}
                )
                assert response2.status_code == 200
                # User 2 should start at 1, not continue from User 1's count
                assert response2.headers["X-Prompts-Used"] == "1"

    @pytest.mark.asyncio 
    async def test_quota_disabled_affects_all_endpoints(self, client, anonymous_client):
        """Test that disabling quotas affects all endpoints consistently."""
        original_setting = APISettings.enable_quota_checking
        APISettings.enable_quota_checking = False

        try:
            # Test authenticated user
            with patch("requests.get") as mock_get:
                mock_response = mock_rw_api_response("Test User")
                mock_get.return_value = mock_response

                # /auth/me should have quota keys but set to null when disabled
                auth_response = await client.get(
                    "/api/auth/me",
                    headers={"Authorization": "Bearer test-token"}
                )
                assert auth_response.status_code == 200
                auth_data = auth_response.json()
                assert auth_data["promptsUsed"] is None
                assert auth_data["promptQuota"] is None

                # /api/chat should not have quota headers
                with patch("src.api.app.stream_chat") as mock_stream:
                    mock_stream.return_value = iter([b'{"response": "Hello!"}\\n'])

                    chat_response = await client.post(
                        "/api/chat",
                        json={"query": "Test message", "thread_id": "test-thread-123"},
                        headers={"Authorization": "Bearer test-token"}
                    )
                    assert chat_response.status_code == 200
                    assert "X-Prompts-Used" not in chat_response.headers
                    assert "X-Prompts-Quota" not in chat_response.headers

            # Test anonymous user
            with patch("src.api.app.stream_chat") as mock_stream:
                mock_stream.return_value = iter([b'{"response": "Hello!"}\\n'])

                anon_response = await anonymous_client.post(
                    "/api/chat",
                    json={"query": "Test message", "thread_id": "test-thread-456"}
                )
                assert anon_response.status_code == 200
                assert "X-Prompts-Used" not in anon_response.headers
                assert "X-Prompts-Quota" not in anon_response.headers

        finally:
            APISettings.enable_quota_checking = original_setting

    @pytest.mark.asyncio
    async def test_admin_vs_regular_user_quota_differences(self, client):
        """Test that admin and regular users have different quota limits."""
        # Test regular user
        with patch("requests.get") as mock_get:
            mock_response = mock_rw_api_response("Test User")
            mock_get.return_value = mock_response

            regular_auth_response = await client.get(
                "/api/auth/me",
                headers={"Authorization": "Bearer regular-token"}
            )
            assert regular_auth_response.status_code == 200
            regular_data = regular_auth_response.json()
            regular_quota = regular_data["promptQuota"]

        # Test admin user
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

            admin_auth_response = await client.get(
                "/api/auth/me",
                headers={"Authorization": "Bearer admin-token"}
            )
            assert admin_auth_response.status_code == 200
            admin_data = admin_auth_response.json()
            admin_quota = admin_data["promptQuota"]

        # Admin should have higher quota
        assert admin_quota > regular_quota
        assert admin_quota == APISettings.admin_user_daily_quota
        assert regular_quota == APISettings.regular_user_daily_quota