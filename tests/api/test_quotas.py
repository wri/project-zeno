"""Tests for quota functionality in authenticated-only mode."""

from unittest.mock import patch

import pytest

from src.api.config import APISettings
from tests.api.mock import mock_rw_api_response


@pytest.fixture(autouse=True)
def clear_cache():
    from src.api.auth.dependencies import _user_info_cache

    _user_info_cache.clear()


@pytest.mark.asyncio
async def test_auth_me_includes_quota_info_when_enabled(client):
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = mock_client_class.return_value.__aenter__.return_value
        mock_client.get.return_value = mock_rw_api_response("Test User")

        response = await client.get(
            "/api/auth/me", headers={"Authorization": "Bearer test-token"}
        )

    assert response.status_code == 200
    data = response.json()
    assert data["promptsUsed"] == 0
    assert data["promptQuota"] == APISettings.regular_user_daily_quota


@pytest.mark.asyncio
async def test_chat_quota_headers_for_authenticated_user(client):
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = mock_client_class.return_value.__aenter__.return_value
        mock_client.get.return_value = mock_rw_api_response("Test User")

        with patch("src.api.routers.chat.stream_chat") as mock_stream:
            mock_stream.return_value = iter([b'{"response": "Hello!"}\n'])
            response = await client.post(
                "/api/chat",
                json={"query": "Test message", "thread_id": "quota-thread"},
                headers={"Authorization": "Bearer test-token"},
            )

    assert response.status_code == 200
    assert response.headers["X-Prompts-Used"] == "1"
    assert response.headers["X-Prompts-Quota"] == str(
        APISettings.regular_user_daily_quota
    )


@pytest.mark.asyncio
async def test_quota_endpoint_requires_auth(client):
    response = await client.get("/api/quota")
    assert response.status_code == 401
