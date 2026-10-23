"""Tests for POST /api/alerts/list with the alerts service faked."""

import asyncio
from datetime import date, datetime

import pytest
import structlog
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth.dependencies import require_auth
from src.api.routers import alerts as alerts_router
from src.api.schemas import UserModel
from src.api.services.alerts_list import (
    AlertsList,
    AlertsWeek,
    DailyAlert,
    InvalidWindowError,
    UnexpectedAlertsDataError,
    UnsupportedAreaError,
)
from src.api.services.dashboard_alerts import (
    AlertsUnavailableError,
    AnalyticsAlertsSource,
)

TODAY = date(2026, 10, 16)
BODY = {
    "source": "gadm",
    "src_id": "BRA.16.137_2",
    "subtype": "district-county",
    "start_date": "2026-09-16",
    "end_date": "2026-10-16",
}
ALERTS = AlertsList(
    data_to=date(2026, 10, 12),
    latest_alert_date=date(2026, 10, 13),
    start_date=date(2026, 9, 16),
    end_date=TODAY,
    new_week=AlertsWeek(date(2026, 10, 7), date(2026, 10, 13)),
    rows=[
        DailyAlert(date(2026, 10, 9), 12.5, 3.0, new=True),
        DailyAlert(date(2026, 9, 20), 1.5, 0.0, new=False),
    ],
)
UPSTREAM = "Failed to pull ... payload: {'aoi': ...}, response: secret"


class FakeService:
    def __init__(self, result=ALERTS, error=None, delay=0.0):
        self.result = result
        self.error = error
        self.delay = delay
        self.calls = []

    async def list(
        self, aoi, start=None, end=None, *, today, land_filter=None
    ):
        self.calls.append(
            {
                "aoi": aoi,
                "start": start,
                "end": end,
                "today": today,
                "land_filter": land_filter,
            }
        )
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.result


def _client(service: FakeService) -> TestClient:
    app = FastAPI()
    app.include_router(alerts_router.router)
    app.dependency_overrides[require_auth] = lambda: UserModel(
        id="u1",
        name="User",
        email="user@example.org",
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )
    app.dependency_overrides[alerts_router.get_alerts_list_service] = (
        lambda: service
    )
    app.dependency_overrides[alerts_router.get_today] = lambda: TODAY
    return TestClient(app)


def _post(service, body=BODY):
    return _client(service).post("/api/alerts/list", json=body)


def test_lists_the_alert_days():
    response = _post(FakeService())

    assert response.status_code == 200
    assert response.json() == {
        "data_to": "2026-10-12",
        "latest_alert_date": "2026-10-13",
        "start_date": "2026-09-16",
        "end_date": "2026-10-16",
        "new_week": {"start_date": "2026-10-07", "end_date": "2026-10-13"},
        "total_area_ha": 17.0,
        "rows": [
            {
                "alert_date": "2026-10-09",
                "high_ha": 12.5,
                "highest_ha": 3.0,
                "total_ha": 15.5,
                "new": True,
            },
            {
                "alert_date": "2026-09-20",
                "high_ha": 1.5,
                "highest_ha": 0.0,
                "total_ha": 1.5,
                "new": False,
            },
        ],
    }


def test_the_service_reads_the_latest_alert_date_from_the_analytics_api():
    service = alerts_router.get_alerts_list_service()

    assert isinstance(service.latest, AnalyticsAlertsSource)


def test_no_data_in_the_period_is_a_null_data_date():
    empty = AlertsList(
        data_to=None,
        latest_alert_date=None,
        start_date=date(2026, 9, 16),
        end_date=TODAY,
        new_week=AlertsWeek(date(2026, 10, 4), date(2026, 10, 10)),
        rows=[],
    )

    response = _post(FakeService(result=empty))

    assert response.status_code == 200
    body = response.json()
    assert (body["data_to"], body["latest_alert_date"]) == (None, None)
    assert (body["end_date"], body["rows"]) == ("2026-10-16", [])


def test_passes_the_area_the_dates_and_today():
    service = FakeService()

    _post(service)

    assert service.calls == [
        {
            "aoi": {
                "source": "gadm",
                "src_id": "BRA.16.137_2",
                "subtype": "district-county",
            },
            "start": date(2026, 9, 16),
            "end": TODAY,
            "today": TODAY,
            "land_filter": None,
        }
    ]


def test_the_dates_are_optional():
    service = FakeService()
    body = {k: v for k, v in BODY.items() if not k.endswith("_date")}

    response = _post(service, body)

    assert response.status_code == 200
    (call,) = service.calls
    assert (call["start"], call["end"]) == (None, None)


@pytest.mark.parametrize("land_filter", ["natural_lands", "natural_forests"])
def test_passes_the_land_filter(land_filter):
    service = FakeService()

    response = _post(service, {**BODY, "land_filter": land_filter})

    assert response.status_code == 200
    (call,) = service.calls
    assert call["land_filter"] == land_filter


@pytest.mark.parametrize(
    "body",
    [BODY, {**BODY, "land_filter": None}],
    ids=["absent", "null"],
)
def test_no_land_filter_is_all_land(body):
    service = FakeService()

    response = _post(service, body)

    assert response.status_code == 200
    (call,) = service.calls
    assert call["land_filter"] is None


@pytest.mark.parametrize("land_filter", ["intact_forest", "Natural_lands", ""])
def test_an_unknown_land_filter_is_422(land_filter):
    service = FakeService()

    response = _post(service, {**BODY, "land_filter": land_filter})

    assert response.status_code == 422
    assert service.calls == []


@pytest.mark.parametrize(
    "error",
    [
        UnsupportedAreaError("Not for 'municipality' areas."),
        InvalidWindowError("The period is longer than 365 days."),
    ],
    ids=["unsupported-area", "invalid-period"],
)
def test_a_request_the_service_refuses_is_422_with_its_message(error):
    response = _post(FakeService(error=error))

    assert response.status_code == 422
    assert response.json() == {"detail": str(error)}


@pytest.mark.parametrize(
    "change",
    [
        {"subtype": None},
        {"src_id": ""},
        {"src_id": "x" * 129},
        {"source": ""},
        {"start_date": "16/09/2026"},
    ],
    ids=[
        "no-subtype",
        "empty-src-id",
        "long-src-id",
        "empty-source",
        "bad-date",
    ],
)
def test_a_malformed_body_is_422(change):
    service = FakeService()
    body = {k: v for k, v in {**BODY, **change}.items() if v is not None}

    response = _post(service, body)

    assert response.status_code == 422
    assert service.calls == []


@pytest.mark.parametrize(
    "error, event",
    [
        (AlertsUnavailableError(UPSTREAM), "alerts_list_unavailable"),
        (UnexpectedAlertsDataError(UPSTREAM), "alerts_list_unexpected_data"),
    ],
    ids=["failed-pull", "unreadable-result"],
)
def test_an_analytics_failure_is_502_with_a_fixed_message(error, event):
    with structlog.testing.capture_logs() as logs:
        response = _post(FakeService(error=error))

    assert response.status_code == 502
    assert response.json() == {
        "detail": alerts_router.ALERTS_UNAVAILABLE_MESSAGE
    }
    assert "secret" not in response.text
    (record,) = [r for r in logs if r["event"] == event]
    assert record["src_id"] == "BRA.16.137_2"


def test_the_upstream_message_is_logged():
    with structlog.testing.capture_logs() as logs:
        _post(FakeService(error=AlertsUnavailableError(UPSTREAM)))

    (record,) = [r for r in logs if r["event"] == "alerts_list_unavailable"]
    assert record["error"] == UPSTREAM


def test_a_slow_analytics_answer_is_502(monkeypatch):
    monkeypatch.setattr(alerts_router, "ALERTS_LIST_TIMEOUT_SECONDS", 0.01)

    with structlog.testing.capture_logs() as logs:
        response = _post(FakeService(delay=1.0))

    assert response.status_code == 502
    assert response.json() == {
        "detail": alerts_router.ALERTS_UNAVAILABLE_MESSAGE
    }
    assert [r for r in logs if r["event"] == "alerts_list_timeout"]
