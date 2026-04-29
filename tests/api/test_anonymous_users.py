"""Tests asserting anonymous access is disabled."""

import pytest


@pytest.mark.asyncio
async def test_anonymous_user_cannot_access_chat_endpoint(client):
    response = await client.post(
        "/api/chat",
        json={"query": "Hello", "thread_id": "anon-thread"},
    )
    assert response.status_code == 401
    assert "Missing Bearer token" in response.json()["detail"]


@pytest.mark.asyncio
async def test_anonymous_user_cannot_access_quota_endpoint(client):
    response = await client.get("/api/quota")
    assert response.status_code == 401
    assert "Missing Bearer token" in response.json()["detail"]
