"""Comprehensive tests for quota functionality."""

from unittest.mock import patch

import pytest

from src.utils.config import APISettings

from .mock import mock_rw_api_response


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the user info cache before each test."""
    from src.api import app as api

    api._user_info_cache.clear()


# Remove this fixture - using the one from conftest.py


class TestQuotaFunctionality:
    """Test core quota functionality across endpoints."""

    @pytest.mark.asyncio
    async def test_auth_me_includes_quota_info_when_enabled(self, client):
        """Test that /auth/me includes quota information when enabled."""
        with patch("httpx.AsyncClient") as mock_client_class:
            # Mock the AsyncClient context manager and get method
            mock_client = (
                mock_client_class.return_value.__aenter__.return_value
            )
            mock_client.get.return_value = mock_rw_api_response("Test User")

            response = await client.get(
                "/api/auth/me", headers={"Authorization": "Bearer test-token"}
            )

            assert response.status_code == 200
            data = response.json()
            assert "promptsUsed" in data
            assert "promptQuota" in data
            assert data["promptsUsed"] == 0
            assert data["promptQuota"] == APISettings.regular_user_daily_quota

    @pytest.mark.asyncio
    async def test_auth_me_quota_disabled_returns_null(self, client):
        """Test that /auth/me returns null quota values when disabled."""
        original_setting = APISettings.enable_quota_checking
        APISettings.enable_quota_checking = False

        try:
            with patch("httpx.AsyncClient") as mock_client_class:
                # Mock the AsyncClient context manager and get method
                mock_client = (
                    mock_client_class.return_value.__aenter__.return_value
                )
                mock_client.get.return_value = mock_rw_api_response(
                    "Test User"
                )

                response = await client.get(
                    "/api/auth/me",
                    headers={"Authorization": "Bearer test-token"},
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
        with patch("httpx.AsyncClient") as mock_client_class:
            # Mock the AsyncClient context manager and get method
            mock_client = (
                mock_client_class.return_value.__aenter__.return_value
            )
            mock_client.get.return_value = mock_rw_api_response("Test User")

            # First call
            response1 = await client.get(
                "/api/auth/me", headers={"Authorization": "Bearer test-token"}
            )
            assert response1.status_code == 200
            assert response1.json()["promptsUsed"] == 0

            chat_request = {
                "query": "Hello, world!",
                "thread_id": "test-thread-123",
            }

            # Mock the stream_chat function to avoid actual LLM calls
            with patch("src.api.app.stream_chat") as mock_stream:
                mock_stream.return_value = iter([b'{"response": "Hello!"}\\n'])

                _ = await client.post(
                    "/api/chat",
                    json=chat_request,
                    headers={"Authorization": "Bearer test-token"},
                )

            # Second call
            response2 = await client.get(
                "/api/auth/me", headers={"Authorization": "Bearer test-token"}
            )
            assert response2.status_code == 200
            assert response2.json()["promptsUsed"] == 1

    @pytest.mark.asyncio
    async def test_chat_includes_quota_headers_when_enabled(self, client):
        """Test that /api/chat includes quota headers when enabled."""
        with patch("httpx.AsyncClient") as mock_client_class:
            # Mock the AsyncClient context manager and get method
            mock_client = (
                mock_client_class.return_value.__aenter__.return_value
            )
            mock_client.get.return_value = mock_rw_api_response("Test User")

            with patch("src.api.app.stream_chat") as mock_stream:
                mock_stream.return_value = iter([b'{"response": "Hello!"}\\n'])

                response = await client.post(
                    "/api/chat",
                    json={
                        "query": "Test message",
                        "thread_id": "test-thread-123",
                    },
                    headers={"Authorization": "Bearer test-token"},
                )

                assert response.status_code == 200
                assert "X-Prompts-Used" in response.headers
                assert "X-Prompts-Quota" in response.headers
                assert response.headers["X-Prompts-Used"] == "1"
                assert response.headers["X-Prompts-Quota"] == str(
                    APISettings.regular_user_daily_quota
                )

    @pytest.mark.asyncio
    async def test_chat_excludes_quota_headers_when_disabled(self, client):
        """Test that /api/chat excludes quota headers when disabled."""
        original_setting = APISettings.enable_quota_checking
        APISettings.enable_quota_checking = False

        try:
            with patch("httpx.AsyncClient") as mock_client_class:
                # Mock the AsyncClient context manager and get method
                mock_client = (
                    mock_client_class.return_value.__aenter__.return_value
                )
                mock_client.get.return_value = mock_rw_api_response(
                    "Test User"
                )

                with patch("src.api.app.stream_chat") as mock_stream:
                    mock_stream.return_value = iter(
                        [b'{"response": "Hello!"}\\n']
                    )

                    response = await client.post(
                        "/api/chat",
                        json={
                            "query": "Test message",
                            "thread_id": "test-thread-123",
                        },
                        headers={"Authorization": "Bearer test-token"},
                    )

                    assert response.status_code == 200
                    assert "X-Prompts-Used" not in response.headers
                    assert "X-Prompts-Quota" not in response.headers

        finally:
            APISettings.enable_quota_checking = original_setting

    @pytest.mark.asyncio
    async def test_admin_user_has_higher_quota(self, client):
        """Test that admin users get higher quota limits."""
        with patch("httpx.AsyncClient") as mock_client_class:
            admin_user_data = {
                "id": "test-admin-1",
                "name": "Admin User",
                "email": "admin@wri.org",
                "createdAt": "2024-01-01T00:00:00Z",
                "updatedAt": "2024-01-01T00:00:00Z",
                "userType": "admin",
            }

            class MockAdminResponse:
                def __init__(self):
                    self.status_code = 200
                    self.text = str(admin_user_data)

                def json(self):
                    return admin_user_data

            # Mock the AsyncClient context manager and get method
            mock_client = (
                mock_client_class.return_value.__aenter__.return_value
            )
            mock_client.get.return_value = MockAdminResponse()

            response = await client.get(
                "/api/auth/me", headers={"Authorization": "Bearer test-token"}
            )

            assert response.status_code == 200
            data = response.json()
            assert data["promptQuota"] == APISettings.admin_user_daily_quota

    @pytest.mark.asyncio
    async def test_anonymous_user_quota_tracking(self, anonymous_client):
        """Test that anonymous users get proper quota tracking."""
        # Enable anonymous chat for this test
        original_setting = APISettings.allow_anonymous_chat
        APISettings.allow_anonymous_chat = True

        try:
            response = await anonymous_client.get("/api/quota")
            assert response.status_code == 200
            assert "promptQuota" in response.json()
            assert response.json()["promptsUsed"] == 0

            with patch("src.api.app.stream_chat") as mock_stream:
                mock_stream.return_value = iter([b'{"response": "Hello!"}\\n'])

                response = await anonymous_client.post(
                    "/api/chat",
                    json={
                        "query": "Test message",
                        "thread_id": "test-thread-123",
                    },
                )

                assert response.status_code == 200
                assert "X-Prompts-Used" in response.headers
                assert "X-Prompts-Quota" in response.headers
                assert response.headers["X-Prompts-Used"] == "1"
                assert response.headers["X-Prompts-Quota"] == str(
                    APISettings.anonymous_user_daily_quota
                )
        finally:
            APISettings.allow_anonymous_chat = original_setting

    @pytest.mark.asyncio
    async def test_quota_consistency_across_endpoints(self, client):
        """Test that quota state is consistent between /auth/me and /api/chat."""
        with patch("httpx.AsyncClient") as mock_client_class:
            # Mock the AsyncClient context manager and get method
            mock_client = (
                mock_client_class.return_value.__aenter__.return_value
            )
            mock_client.get.return_value = mock_rw_api_response("Test User")

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
                    json={
                        "query": "Test message",
                        "thread_id": "test-thread-123",
                    },
                    headers={"Authorization": "Bearer test-token"},
                )

                assert chat_response.status_code == 200
                chat_used = int(chat_response.headers["X-Prompts-Used"])
                chat_quota = int(chat_response.headers["X-Prompts-Quota"])

            quota_response = await client.get(
                "/api/quota", headers={"Authorization": "Bearer test-token"}
            )

            # Values should be consistent and incremental
            assert (
                chat_used
                == quota_response.json()["promptsUsed"]
                == auth_used + 1
            )  # auth(1) -> chat(2)
            assert chat_quota == APISettings.regular_user_daily_quota

    @pytest.mark.asyncio
    async def test_quota_exceeded_returns_429(self, client):
        """Test that exceeding quota returns 429 status."""
        # Set very low quota for testing
        original_quota = APISettings.regular_user_daily_quota
        APISettings.regular_user_daily_quota = 1

        try:
            with patch("httpx.AsyncClient") as mock_client_class:
                # Mock the AsyncClient context manager and get method
                mock_client = (
                    mock_client_class.return_value.__aenter__.return_value
                )
                mock_client.get.return_value = mock_rw_api_response(
                    "Test User"
                )

                with patch("src.api.app.stream_chat") as mock_stream:
                    mock_stream.return_value = iter(
                        [b'{"response": "Hello!"}\\n']
                    )

                    # First call should succeed
                    response1 = await client.post(
                        "/api/chat",
                        json={
                            "query": "First message",
                            "thread_id": "test-thread-123",
                        },
                        headers={"Authorization": "Bearer test-token"},
                    )
                    assert response1.status_code == 200

                    # Second call should fail with 429
                    response2 = await client.post(
                        "/api/chat",
                        json={
                            "query": "Second message",
                            "thread_id": "test-thread-123",
                        },
                        headers={"Authorization": "Bearer test-token"},
                    )
                    assert response2.status_code == 429
                    assert (
                        "Daily free limit of 1 exceeded"
                        in response2.json()["detail"]
                    )

        finally:
            APISettings.regular_user_daily_quota = original_quota

    @pytest.mark.asyncio
    async def test_ip_based_quota_enforcement(self):
        """Test that IP-based quota limits are enforced for anonymous users."""
        import uuid

        from httpx import ASGITransport, AsyncClient

        from src.api.app import app

        # Store original settings
        original_ip_quota = APISettings.ip_address_daily_quota
        original_anonymous_setting = APISettings.allow_anonymous_chat

        # Set test configuration
        APISettings.ip_address_daily_quota = 3  # Set to low number for testing
        APISettings.allow_anonymous_chat = True  # Enable anonymous chat

        try:
            # Use a unique IP address for this test to avoid conflicts
            unique_ip = f"10.0.0.{uuid.uuid4().int % 255}"

            # Create two anonymous clients with same unique IP but different sessions
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                headers={
                    "X-API-KEY": "test-nextjs-api-key",
                    "X-ZENO-FORWARDED-FOR": unique_ip,
                    "Authorization": "Bearer noauth:test-session-1",
                },
            ) as client1:
                async with (
                    AsyncClient(
                        transport=ASGITransport(app=app),
                        base_url="http://test",
                        headers={
                            "X-API-KEY": "test-nextjs-api-key",
                            "X-ZENO-FORWARDED-FOR": unique_ip,  # Same unique IP
                            "Authorization": "Bearer noauth:test-session-2",  # Different session
                        },
                    ) as client2
                ):
                    # Mock stream_chat to avoid actual LLM calls
                    with patch("src.api.app.stream_chat") as mock_stream:
                        mock_stream.return_value = iter(
                            [b'{"response": "OK"}\\n']
                        )

                        # Make 3 requests alternating between clients (IP quota is 3)
                        for i in range(3):
                            client = client1 if i % 2 == 0 else client2
                            response = await client.post(
                                "/api/chat",
                                json={
                                    "query": f"Message {i}",
                                    "thread_id": f"thread-{i}",
                                },
                            )
                            assert response.status_code == 200

                        # 4th request should exceed IP quota
                        response = await client1.post(
                            "/api/chat",
                            json={
                                "query": "Should fail",
                                "thread_id": "thread-fail",
                            },
                        )

                        assert response.status_code == 429
                        assert (
                            "exceeded for IP address"
                            in response.json()["detail"]
                        )

        finally:
            # Restore original settings
            APISettings.ip_address_daily_quota = original_ip_quota
            APISettings.allow_anonymous_chat = original_anonymous_setting

    @pytest.mark.asyncio
    async def test_different_ips_have_separate_quotas(self):
        """Test that different IP addresses have separate quota limits."""
        from httpx import ASGITransport, AsyncClient

        from src.api.app import app

        # Enable anonymous chat for this test
        original_setting = APISettings.allow_anonymous_chat
        APISettings.allow_anonymous_chat = True

        try:
            # Create clients with different IP addresses
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                headers={
                    "X-API-KEY": "test-nextjs-api-key",
                    "X-ZENO-FORWARDED-FOR": "192.168.1.10",
                    "Authorization": "Bearer noauth:session-ip1",
                },
            ) as client1:
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                    headers={
                        "X-API-KEY": "test-nextjs-api-key",
                        "X-ZENO-FORWARDED-FOR": "192.168.1.20",  # Different IP
                        "Authorization": "Bearer noauth:session-ip2",
                    },
                ) as client2:
                    with patch("src.api.app.stream_chat") as mock_stream:
                        mock_stream.return_value = iter(
                            [b'{"response": "OK"}\\n']
                        )

                        # Both clients should be able to make requests independently
                        # up to their respective quota limits
                        for i in range(5):  # Make a few requests from each IP
                            response1 = await client1.post(
                                "/api/chat",
                                json={
                                    "query": f"IP1 Message {i}",
                                    "thread_id": f"thread1-{i}",
                                },
                            )
                            assert response1.status_code == 200

                            response2 = await client2.post(
                                "/api/chat",
                                json={
                                    "query": f"IP2 Message {i}",
                                    "thread_id": f"thread2-{i}",
                                },
                            )
                            assert response2.status_code == 200
        finally:
            APISettings.allow_anonymous_chat = original_setting


class TestAPIKeyValidation:
    """Test API key validation for NextJS integration."""

    @pytest.mark.asyncio
    async def test_missing_api_key_blocks_anonymous_requests(self):
        """Test that anonymous requests without X-API-KEY are blocked."""
        from httpx import ASGITransport, AsyncClient

        from src.api.app import app

        # Client missing X-API-KEY header
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={
                "X-ZENO-FORWARDED-FOR": "192.168.1.1",
                "Authorization": "Bearer noauth:test-session",
                # Missing X-API-KEY
            },
        ) as client:
            response = await client.post(
                "/api/chat",
                json={"query": "Test message", "thread_id": "test-thread"},
            )

            assert response.status_code == 403
            assert "Invalid API key from NextJS" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_invalid_api_key_blocks_anonymous_requests(self):
        """Test that anonymous requests with invalid X-API-KEY are blocked."""
        from httpx import ASGITransport, AsyncClient

        from src.api.app import app

        # Client with wrong API key
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={
                "X-API-KEY": "wrong-api-key",  # Invalid key
                "X-ZENO-FORWARDED-FOR": "192.168.1.1",
                "Authorization": "Bearer noauth:test-session",
            },
        ) as client:
            response = await client.post(
                "/api/chat",
                json={"query": "Test message", "thread_id": "test-thread"},
            )

            assert response.status_code == 403
            assert "Invalid API key from NextJS" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_missing_ip_header_blocks_anonymous_requests(self):
        """Test that anonymous requests without X-ZENO-FORWARDED-FOR are blocked."""
        from httpx import ASGITransport, AsyncClient

        from src.api.app import app

        # Client missing IP header
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={
                "X-API-KEY": "test-nextjs-api-key",
                "Authorization": "Bearer noauth:test-session",
                # Missing X-ZENO-FORWARDED-FOR
            },
        ) as client:
            response = await client.post(
                "/api/chat",
                json={"query": "Test message", "thread_id": "test-thread"},
            )

            assert response.status_code == 403
            assert (
                "Missing X-ZENO-FORWARDED-FOR header"
                in response.json()["detail"]
            )

    @pytest.mark.asyncio
    async def test_authenticated_users_dont_need_nextjs_headers(self):
        """Test that authenticated users don't need NextJS-specific headers."""
        from httpx import ASGITransport, AsyncClient

        from src.api.app import app

        # Regular authenticated client without NextJS headers
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={
                "Authorization": "Bearer regular-jwt-token"
                # No X-API-KEY or X-ZENO-FORWARDED-FOR headers
            },
        ) as client:
            with patch("httpx.AsyncClient") as mock_client_class:
                from tests.api.mock import mock_rw_api_response

                # Mock the AsyncClient context manager and get method
                mock_client = (
                    mock_client_class.return_value.__aenter__.return_value
                )
                mock_client.get.return_value = mock_rw_api_response(
                    "Test User"
                )

                with patch("src.api.app.stream_chat") as mock_stream:
                    mock_stream.return_value = iter([b'{"response": "OK"}\\n'])

                    response = await client.post(
                        "/api/chat",
                        json={
                            "query": "Test message",
                            "thread_id": "test-thread",
                        },
                    )

                    # Authenticated users should work without NextJS headers
                    assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_invalid_anonymous_authorization_format(self):
        """Test that invalid anonymous authorization formats are rejected."""
        from httpx import ASGITransport, AsyncClient

        from src.api.app import app

        # Test case 1: Wrong scheme (should be noauth, not anon)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={
                "X-API-KEY": "test-nextjs-api-key",
                "X-ZENO-FORWARDED-FOR": "192.168.1.1",
                "Authorization": "Bearer anon:session-123",  # Wrong scheme
            },
        ) as client:
            response = await client.post(
                "/api/chat",
                json={"query": "Test message", "thread_id": "test-thread"},
            )

            assert response.status_code == 401
            assert (
                "Unauthorized, anonymous users should use 'noauth' scheme"
                in response.json()["detail"]
            )
