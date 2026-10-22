"""Tests for POST /api/alerts/list through the app, with the analytics pull
faked."""

import pytest

from src.api.app import app
from src.api.routers.alerts import get_alerts_list_service
from src.api.services.alerts_list import AlertsListService
from tests.api.test_dashboards import AUTH, _create_user
from tests.unit.api.services.test_alerts_list import FakeHandler, FakeLatest

BODY = {"source": "gadm", "src_id": "BRA.16_1", "subtype": "state-province"}
DATA = {
    "alert_date": ["2026-09-20", "2026-09-20"],
    "alert_confidence": ["high", "low"],
    "area_ha": [1.5, 9.0],
}


@pytest.fixture
def fake_alerts_list_service():
    app.dependency_overrides[get_alerts_list_service] = lambda: (
        AlertsListService(FakeHandler(DATA), FakeLatest())
    )
    yield
    app.dependency_overrides.pop(get_alerts_list_service, None)


@pytest.mark.asyncio
async def test_alerts_list_requires_auth(client, fake_alerts_list_service):
    response = await client.post("/api/alerts/list", json=BODY)

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_alerts_list(client, auth_override, fake_alerts_list_service):
    user = await _create_user("alerts-lister")
    auth_override(user.id)

    response = await client.post(
        "/api/alerts/list",
        headers=AUTH,
        json={**BODY, "start_date": "2026-09-01", "end_date": "2026-09-30"},
    )

    assert response.status_code == 200
    body = response.json()
    # data_to is the area's latest alert date, low confidence included;
    # latest_alert_date is the dataset's.
    assert (
        body["start_date"],
        body["end_date"],
        body["data_to"],
        body["latest_alert_date"],
    ) == ("2026-09-01", "2026-09-30", "2026-09-20", "2026-10-12")
    assert body["rows"] == [
        {
            "alert_date": "2026-09-20",
            "high_ha": 1.5,
            "highest_ha": 0.0,
            "total_ha": 1.5,
            "new": False,
        }
    ]
    assert body["total_area_ha"] == 1.5


@pytest.mark.asyncio
async def test_alerts_list_refuses_an_unsupported_area(
    client, auth_override, fake_alerts_list_service
):
    user = await _create_user("alerts-municipality")
    auth_override(user.id)

    response = await client.post(
        "/api/alerts/list",
        headers=AUTH,
        json={**BODY, "subtype": "municipality"},
    )

    assert response.status_code == 422
    assert "municipality" in response.json()["detail"]
