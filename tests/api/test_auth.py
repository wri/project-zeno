"""Tests for authentication-related endpoints."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from src.api.auth.dependencies import _user_info_cache
from src.api.cli import create_api_key, create_machine_user
from src.api.data_models import UserOrm
from tests.api.mock import mock_rw_api_response, mock_rw_me_response
from tests.conftest import async_session_maker


@pytest.fixture(autouse=True)
def clear_cache():
    _user_info_cache.clear()


@pytest.mark.asyncio
async def test_auth_me_requires_bearer_token(client):
    response = await client.get("/api/auth/me")
    assert response.status_code == 401
    assert "Missing Bearer token" in response.json()["detail"]


@pytest.mark.asyncio
async def test_auth_me_returns_user_with_valid_token(client):
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = mock_client_class.return_value.__aenter__.return_value
        mock_client.get.return_value = mock_rw_api_response("Test User")

        response = await client.get(
            "/api/auth/me", headers={"Authorization": "Bearer test-token"}
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "Test User"
    assert payload["email"] == "test@developmentseed.org"


@pytest.mark.asyncio
async def test_auth_me_creates_user_without_whitelist_gates(client):
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = mock_client_class.return_value.__aenter__.return_value
        mock_response = mock_rw_api_response("Public User")
        mock_response.json_data["id"] = "public-user-1"
        mock_response.json_data["email"] = "public@example.org"
        mock_client.get.return_value = mock_response

        response = await client.get(
            "/api/auth/me", headers={"Authorization": "Bearer test-token"}
        )

    assert response.status_code == 200
    assert response.json()["id"] == "public-user-1"


# --- Signup origin: first_seen_at and rw_apps -------------------------------


async def _login(client, rw_me_response, token="test-token"):
    """GET /api/auth/me with RW's /auth/user/me answering ``rw_me_response``."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = mock_client_class.return_value.__aenter__.return_value
        mock_client.get.return_value = rw_me_response
        return await client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
        )


async def _user_row(user_id):
    async with async_session_maker() as session:
        return await session.get(UserOrm, user_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "apps", [["gfw"], ["gnw"]], ids=["existing-gfw-user", "organic"]
)
async def test_first_login_records_rw_apps_and_first_seen_at(client, apps):
    before = datetime.now(timezone.utc)
    response = await _login(
        client, mock_rw_me_response("rw-origin", {"apps": apps})
    )
    after = datetime.now(timezone.utc)

    assert response.status_code == 200
    data = response.json()
    assert data["rwApps"] == apps
    first_seen_at = datetime.fromisoformat(data["firstSeenAt"])
    assert before <= first_seen_at <= after
    # createdAt stays the RW account's creation date.
    assert data["createdAt"].startswith("2019-05-01T10:00:00")

    row = await _user_row("rw-origin")
    assert row.rw_apps == apps
    assert row.first_seen_at == first_seen_at


@pytest.mark.asyncio
async def test_first_login_without_extra_user_data_leaves_apps_null(client):
    before = datetime.now(timezone.utc)
    response = await _login(client, mock_rw_me_response("rw-no-apps"))

    assert response.status_code == 200
    assert response.json()["rwApps"] is None
    assert datetime.fromisoformat(response.json()["firstSeenAt"]) >= before
    row = await _user_row("rw-no-apps")
    assert row.rw_apps is None
    assert row.first_seen_at is not None


@pytest.mark.asyncio
async def test_first_seen_at_comes_from_the_server_clock(client):
    rw_me = mock_rw_me_response("rw-clock", {"apps": ["gfw"]})
    rw_me.json_data["firstSeenAt"] = "2000-01-01T00:00:00Z"
    before = datetime.now(timezone.utc)

    response = await _login(client, rw_me)

    assert datetime.fromisoformat(response.json()["firstSeenAt"]) >= before


@pytest.mark.asyncio
async def test_later_logins_never_change_signup_origin(client):
    first = await _login(
        client, mock_rw_me_response("rw-again", {"apps": ["gnw"]}), "token-1"
    )
    # A later login on a new token, after the account also joined GFW.
    second = await _login(
        client,
        mock_rw_me_response("rw-again", {"apps": ["gnw", "gfw"]}),
        "token-2",
    )

    assert second.status_code == 200
    assert second.json()["rwApps"] == ["gnw"]
    assert second.json()["firstSeenAt"] == first.json()["firstSeenAt"]
    row = await _user_row("rw-again")
    assert row.rw_apps == ["gnw"]


@pytest.mark.asyncio
async def test_profile_update_cannot_set_signup_origin(client):
    first = await _login(
        client, mock_rw_me_response("rw-patch", {"apps": ["gfw"]})
    )

    response = await client.patch(
        "/api/auth/profile",
        headers={"Authorization": "Bearer test-token"},
        json={
            "first_name": "Ada",
            "first_seen_at": "2000-01-01T00:00:00Z",
            "firstSeenAt": "2000-01-01T00:00:00Z",
            "rw_apps": ["forged"],
            "rwApps": ["forged"],
        },
    )

    # Unknown keys are ignored, as for any other non-profile field.
    assert response.status_code == 200
    assert response.json()["firstName"] == "Ada"
    assert response.json()["rwApps"] == ["gfw"]
    assert response.json()["firstSeenAt"] == first.json()["firstSeenAt"]


@pytest.mark.asyncio
async def test_machine_user_has_no_signup_origin(client):
    async with async_session_maker() as session:
        machine = await create_machine_user(
            session, "origin-bot", "origin-bot@example.org"
        )
        token, _ = await create_api_key(session, machine.id, "test")

    response = await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert response.json()["firstSeenAt"] is None
    assert response.json()["rwApps"] is None
