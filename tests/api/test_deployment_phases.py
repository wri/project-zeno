"""Regression checks for authenticated-only API behavior."""

from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_chat_requires_authentication(client):
    response = await client.post(
        "/api/chat",
        json={"query": "Hello", "thread_id": "auth-required-thread"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_chat_allows_authenticated_user(client, auth_override):
    auth_override("test-user-wri")
    with patch("src.api.routers.chat.stream_chat") as mock_stream:
        mock_stream.return_value = iter([b'{"response": "Hello!"}\n'])
        response = await client.post(
            "/api/chat",
            json={"query": "Hello", "thread_id": "auth-thread"},
        )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_metadata_no_longer_exposes_signup_or_anonymous_flags(client):
    response = await client.get("/api/metadata")
    assert response.status_code == 200
    data = response.json()
    assert "is_signup_open" not in data
    assert "allow_anonymous_chat" not in data
