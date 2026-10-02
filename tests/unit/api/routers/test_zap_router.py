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


def _client(user_type: UserType, monkeypatch) -> TestClient:
    async def fake_plan(prompt, current, user_id):
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
