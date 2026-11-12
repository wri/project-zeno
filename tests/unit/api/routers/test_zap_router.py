"""Tests for the zap router: admins and superusers only."""

from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth.dependencies import require_auth
from src.api.data_models import UserType
from src.api.routers import zap as zap_router
from src.api.schemas import UserModel
from src.api.services.zap.models import ZapPlan


def _client(
    user_type: UserType, monkeypatch, sent: list | None = None
) -> TestClient:
    async def fake_plan(prompt, current, user_id, choose=None):
        if sent is not None:
            sent.append((current, user_id))
        return ZapPlan(steps=[], decisions=[], notes=[])

    monkeypatch.setattr(zap_router, "plan_zap", fake_plan)
    app = FastAPI()
    app.include_router(zap_router.router)
    app.dependency_overrides[require_auth] = lambda: UserModel(
        id="u1",
        name="User",
        email="user@example.org",
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
        user_type=user_type,
    )
    return TestClient(app)


@pytest.mark.parametrize(
    ("user_type", "status"),
    [
        (UserType.ADMIN, 200),
        (UserType.SUPERUSER, 200),
        (UserType.REGULAR, 403),
        (UserType.PRO, 403),
        (UserType.MACHINE, 403),
    ],
)
def test_zap_is_for_admins_only(user_type, status, monkeypatch):
    client = _client(user_type, monkeypatch)

    response = client.post("/api/zap", json={"prompt": "fires in Bolivia"})

    assert response.status_code == status


def test_the_page_and_the_dashboard_id_reach_the_planner(monkeypatch):
    sent = []
    client = _client(UserType.ADMIN, monkeypatch, sent)

    response = client.post(
        "/api/zap",
        json={
            "prompt": "add a tree cover loss chart",
            "current": {"page": "dashboard", "dashboard_id": "d1"},
        },
    )

    assert response.status_code == 200
    current, user_id = sent[0]
    assert current.page == "dashboard"
    assert current.dashboard_id == "d1"
    assert user_id == "u1"


def test_a_request_with_no_page_is_a_map_request(monkeypatch):
    sent = []
    client = _client(UserType.ADMIN, monkeypatch, sent)

    response = client.post("/api/zap", json={"prompt": "fires in Bolivia"})

    assert response.status_code == 200
    assert sent[0][0].page is None
    # The new plan fields are optional: an empty plan sends them as null.
    body = response.json()
    assert body["tier"] is None
    assert body["needs_confirmation"] is None


def test_an_unknown_page_is_rejected(monkeypatch):
    client = _client(UserType.ADMIN, monkeypatch)

    response = client.post(
        "/api/zap", json={"prompt": "x", "current": {"page": "settings"}}
    )

    assert response.status_code == 422
