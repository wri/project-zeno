import asyncio
from datetime import date
from uuid import uuid4

import httpx
import pytest
import structlog

from src.agent.datasets.handlers.analytics_handler import INTEGRATED_ALERTS_ID
from src.agent.datasets.handlers.base import DataPullResult, DataSourceHandler
from src.api.services import dashboard_alerts
from src.api.services.dashboard_alerts import (
    AlertsUnavailableError,
    AnalyticsAlertsSource,
    DashboardAlerts,
    DashboardAlertsService,
    InvalidPeriodError,
    latest_alert_week,
)

PARANA = {
    "source": "gadm",
    "src_id": "BRA.16_1",
    "subtype": "state-province",
    "name": "Paraná",
}
PARA = {
    "source": "gadm",
    "src_id": "BRA.14_1",
    "subtype": "state-province",
    "name": "Pará",
}
MY_AREA = {
    "source": "custom",
    "src_id": "b89bcc67-fcbd-4cf8-8d08-38efdcba0cd2",
    "subtype": "custom-area",
    "name": "Heart of the Amazon",
}
RIVER_FARM = {
    "source": "custom",
    "src_id": "f1ab3512-e8b8-4a28-abfc-3dbb745fff21",
    "subtype": "custom-area",
    "name": "River farm",
}
CURITIBA = {
    "source": "gadm",
    "src_id": "BRA.16.137.1_1",
    "subtype": "municipality",
    "name": "Curitiba",
}
MONDAY = date(2026, 10, 12)
WEEK = (date(2026, 10, 4), date(2026, 10, 10))
LATEST_ALERT_DATE = date(2026, 10, 9)
LATEST_PERIOD = (date(2026, 10, 3), LATEST_ALERT_DATE)
BASE_URL = "https://analytics.example.com"
LATEST_URL = BASE_URL + "/v0/land_change/integrated_alerts/latest"


class FakeAlertsSource:
    def __init__(
        self,
        area_ha_by_src_id=None,
        fail=False,
        latest=LATEST_ALERT_DATE,
        failing=(),
        hanging=(),
    ):
        self.area_ha = area_ha_by_src_id or {}
        self.fail = fail
        self.latest = latest
        # Requests that include one of these src_ids fail.
        self.failing = set(failing)
        # Requests that include one of these src_ids never answer.
        self.hanging = set(hanging)
        self.calls = []
        self.cancelled = []
        self.in_flight = 0
        self.most_in_flight = 0

    async def area_ha_by_src_id(self, aois, start, end):
        self.calls.append((aois, start, end))
        src_ids = {aoi["src_id"] for aoi in aois}
        self.in_flight += 1
        self.most_in_flight = max(self.most_in_flight, self.in_flight)
        try:
            # Yield, so that concurrent requests overlap.
            await asyncio.sleep(0)
            if self.hanging & src_ids:
                await asyncio.Event().wait()
            if self.fail or self.failing & src_ids:
                raise AlertsUnavailableError("timed out")
            return self.area_ha
        except asyncio.CancelledError:
            self.cancelled.extend(sorted(src_ids))
            raise
        finally:
            self.in_flight -= 1

    async def latest_alert_date(self):
        if self.latest is None:
            raise AlertsUnavailableError("no latest alert date")
        return self.latest


class FakeHandler(DataSourceHandler):
    def __init__(self, result: DataPullResult):
        self.result = result
        self.last_call = {}

    def can_handle(self, dataset) -> bool:
        return True

    async def pull_data(
        self,
        query,
        dataset,
        start_date,
        end_date,
        change_over_time_query,
        aois,
    ):
        self.last_call = {
            "dataset": dataset,
            "start_date": start_date,
            "end_date": end_date,
        }
        for aoi in aois:
            aoi["src_id"] = aoi["src_id"][:-2]
        return self.result


def _service(source):
    return DashboardAlertsService(source, today=lambda: MONDAY)


@pytest.fixture(autouse=True)
def clear_latest_alert_date_cache():
    dashboard_alerts._latest_alert_date_cache.clear()
    yield
    dashboard_alerts._latest_alert_date_cache.clear()


def _latest_source(handler_response):
    """An analytics source whose HTTP requests go to handler_response."""
    requests = []

    def handle(request):
        requests.append(request)
        return handler_response(request)

    source = AnalyticsAlertsSource(
        FakeHandler(DataPullResult(success=True, data={}, message="")),
        BASE_URL,
        transport=httpx.MockTransport(handle),
    )
    return source, requests


@pytest.mark.parametrize(
    "today, expected",
    [
        (MONDAY, WEEK),
        (date(2026, 10, 11), WEEK),
        (date(2026, 10, 10), (date(2026, 9, 27), date(2026, 10, 3))),
    ],
    ids=["monday", "sunday", "saturday-week-not-over"],
)
def test_latest_alert_week_ends_on_last_full_saturday(today, expected):
    assert latest_alert_week(today) == expected


@pytest.mark.asyncio
async def test_summarize_reports_every_dashboard_from_one_request():
    source = FakeAlertsSource({"BRA.16_1": 12.5})
    parana, also_parana, para = uuid4(), uuid4(), uuid4()

    report = await _service(source).summarize(
        {parana: PARANA, also_parana: PARANA, para: PARA}
    )

    assert source.calls == [([PARANA, PARA], *LATEST_PERIOD)]
    assert (report.start_date, report.end_date) == LATEST_PERIOD
    assert report.dashboards == {
        parana: DashboardAlerts(integrated_alerts=12.5),
        also_parana: DashboardAlerts(integrated_alerts=12.5),
        para: DashboardAlerts(integrated_alerts=0.0),
    }


@pytest.mark.asyncio
async def test_summarize_uses_the_requested_period():
    source = FakeAlertsSource()
    period = (date(2026, 9, 1), date(2026, 9, 30))

    report = await _service(source).summarize({uuid4(): PARANA}, *period)

    assert source.calls == [([PARANA], *period)]
    assert (report.start_date, report.end_date) == period


@pytest.mark.asyncio
async def test_summarize_falls_back_to_the_latest_full_week():
    source = FakeAlertsSource(latest=None)

    report = await _service(source).summarize({uuid4(): PARANA})

    assert source.calls == [([PARANA], *WEEK)]
    assert (report.start_date, report.end_date) == WEEK


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "start, end",
    [(date(2026, 9, 1), None), (None, date(2026, 9, 30))],
    ids=["start-only", "end-only"],
)
async def test_summarize_rejects_one_date_without_the_other(start, end):
    with pytest.raises(InvalidPeriodError):
        await _service(FakeAlertsSource()).summarize(
            {uuid4(): PARANA}, start, end
        )


@pytest.mark.asyncio
async def test_summarize_rejects_a_start_after_the_end():
    with pytest.raises(InvalidPeriodError):
        await _service(FakeAlertsSource()).summarize(
            {uuid4(): PARANA}, date(2026, 10, 10), date(2026, 10, 4)
        )


@pytest.mark.asyncio
async def test_summarize_reports_a_failed_request_on_every_dashboard():
    parana, para = uuid4(), uuid4()

    report = await _service(FakeAlertsSource(fail=True)).summarize(
        {parana: PARANA, para: PARA}
    )

    failed = DashboardAlerts(
        integrated_alerts=None,
        errors={"integrated_alerts": "Integrated alerts data is unavailable"},
    )
    assert report.dashboards == {parana: failed, para: failed}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "aoi",
    [
        None,
        {**PARANA, "source": "wdpa", "subtype": "protected-area"},
    ],
    ids=["no-aoi", "protected-area"],
)
async def test_summarize_leaves_out_unsupported_aois(aoi):
    source = FakeAlertsSource()

    report = await _service(source).summarize({uuid4(): aoi})

    assert report.dashboards == {}
    assert source.calls == []


def _requested_src_ids(source):
    """The src_ids of each request, in a stable order."""
    return sorted(
        tuple(aoi["src_id"] for aoi in aois) for aois, *_ in source.calls
    )


@pytest.mark.asyncio
async def test_summarize_pulls_admin_areas_together_and_custom_areas_alone():
    source = FakeAlertsSource(
        {"BRA.16_1": 12.5, MY_AREA["src_id"]: 3.0, RIVER_FARM["src_id"]: 0.5}
    )
    parana, para, mine, also_mine, farm = (uuid4() for _ in range(5))

    report = await _service(source).summarize(
        {
            parana: PARANA,
            para: PARA,
            mine: MY_AREA,
            also_mine: MY_AREA,
            farm: RIVER_FARM,
        }
    )

    assert _requested_src_ids(source) == sorted(
        [
            ("BRA.16_1", "BRA.14_1"),
            (MY_AREA["src_id"],),
            (RIVER_FARM["src_id"],),
        ]
    )
    assert report.dashboards == {
        parana: DashboardAlerts(integrated_alerts=12.5),
        para: DashboardAlerts(integrated_alerts=0.0),
        mine: DashboardAlerts(integrated_alerts=3.0),
        also_mine: DashboardAlerts(integrated_alerts=3.0),
        farm: DashboardAlerts(integrated_alerts=0.5),
    }


# The API computes admin levels 3 to 5 on the fly, and never in a request
# with levels 0 to 2.
@pytest.mark.asyncio
async def test_summarize_pulls_each_admin_area_below_district_alone():
    source = FakeAlertsSource({"BRA.16_1": 12.5, CURITIBA["src_id"]: 1.5})
    parana, para, curitiba = uuid4(), uuid4(), uuid4()

    report = await _service(source).summarize(
        {parana: PARANA, para: PARA, curitiba: CURITIBA}
    )

    assert _requested_src_ids(source) == sorted(
        [("BRA.16_1", "BRA.14_1"), (CURITIBA["src_id"],)]
    )
    assert report.dashboards[curitiba] == DashboardAlerts(
        integrated_alerts=1.5
    )


@pytest.mark.asyncio
async def test_summarize_keeps_the_other_totals_when_a_custom_area_fails():
    source = FakeAlertsSource(
        {"BRA.16_1": 12.5, MY_AREA["src_id"]: 3.0},
        failing={RIVER_FARM["src_id"]},
    )
    parana, mine, farm = uuid4(), uuid4(), uuid4()

    report = await _service(source).summarize(
        {parana: PARANA, mine: MY_AREA, farm: RIVER_FARM}
    )

    assert report.dashboards == {
        parana: DashboardAlerts(integrated_alerts=12.5),
        mine: DashboardAlerts(integrated_alerts=3.0),
        farm: dashboard_alerts.unavailable(),
    }


@pytest.mark.asyncio
async def test_summarize_pulls_a_limited_number_of_custom_areas_at_once():
    source = FakeAlertsSource()
    count = dashboard_alerts.CUSTOM_AREAS_CONCURRENCY + 4
    areas = {
        uuid4(): {**MY_AREA, "src_id": str(uuid4())} for _ in range(count)
    }

    report = await _service(source).summarize(areas)

    assert len(source.calls) == count
    assert source.most_in_flight == dashboard_alerts.CUSTOM_AREAS_CONCURRENCY
    assert set(report.dashboards) == set(areas)


@pytest.mark.asyncio
async def test_summarize_stops_waiting_for_slow_custom_areas():
    source = FakeAlertsSource(
        {"BRA.16_1": 12.5, MY_AREA["src_id"]: 3.0},
        hanging={RIVER_FARM["src_id"]},
    )
    service = DashboardAlertsService(
        source, today=lambda: MONDAY, custom_areas_timeout_seconds=0.05
    )
    parana, mine, farm = uuid4(), uuid4(), uuid4()

    with structlog.testing.capture_logs() as logs:
        report = await service.summarize(
            {parana: PARANA, mine: MY_AREA, farm: RIVER_FARM}
        )

    assert report.dashboards == {
        parana: DashboardAlerts(integrated_alerts=12.5),
        mine: DashboardAlerts(integrated_alerts=3.0),
        farm: dashboard_alerts.unavailable(),
    }
    assert source.cancelled == [RIVER_FARM["src_id"]]
    [record] = [
        log
        for log in logs
        if log["event"] == "dashboard_alerts_custom_areas_timeout"
    ]
    assert record["log_level"] == "warning"
    assert record["custom_area_ids"] == [RIVER_FARM["src_id"]]
    # Custom area names are user text, so they stay out of the logs.
    assert RIVER_FARM["name"] not in str(record)


@pytest.mark.asyncio
async def test_analytics_source_sums_area_by_aoi():
    handler = FakeHandler(
        DataPullResult(
            success=True,
            data={
                "aoi_id": ["BRA.16", "BRA.14", "BRA.14"],
                "alert_confidence": ["high", "high", "highest"],
                "area_ha": [1.25, 2.5, 0.5],
            },
            message="",
        )
    )
    aois = [dict(PARANA), dict(PARA)]

    area_ha = await AnalyticsAlertsSource(handler, BASE_URL).area_ha_by_src_id(
        aois, *WEEK
    )

    assert area_ha == {"BRA.16_1": 1.25, "BRA.14_1": 3.0}
    assert aois == [PARANA, PARA]
    assert handler.last_call == {
        "dataset": {"dataset_id": INTEGRATED_ALERTS_ID},
        "start_date": "2026-10-04",
        "end_date": "2026-10-10",
    }


def _analytics_source(data):
    """An analytics source whose pull returns this column-oriented result."""
    handler = FakeHandler(DataPullResult(success=True, data=data, message=""))
    return AnalyticsAlertsSource(handler, BASE_URL)


@pytest.mark.asyncio
async def test_analytics_source_leaves_out_low_confidence_alerts():
    source = _analytics_source(
        {
            "aoi_id": ["BRA.16", "BRA.16", "BRA.14"],
            "alert_confidence": ["low", "high", "low"],
            "area_ha": [100.0, 1.5, 7.0],
        }
    )

    area_ha = await source.area_ha_by_src_id([dict(PARANA), dict(PARA)], *WEEK)

    assert area_ha == {"BRA.16_1": 1.5}


@pytest.mark.asyncio
async def test_analytics_source_counts_a_missing_area_as_zero():
    source = _analytics_source(
        {
            "aoi_id": ["BRA.16", "BRA.16"],
            "alert_confidence": ["high", "highest"],
            "area_ha": [None, 2.0],
        }
    )

    area_ha = await source.area_ha_by_src_id([dict(PARANA)], *WEEK)

    assert area_ha == {"BRA.16_1": 2.0}


@pytest.mark.asyncio
async def test_analytics_source_reads_an_empty_result_as_no_alerts():
    # The analytics API's answer for an area without alerts, plus the name
    # column the handler adds.
    source = _analytics_source(
        {
            "aoi_id": [],
            "alert_date": [],
            "alert_confidence": [],
            "area_ha": [],
            "aoi_type": [],
            "name": [],
        }
    )

    assert await source.area_ha_by_src_id([dict(PARANA)], *WEEK) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data",
    [
        {
            "aoi_id": ["BRA.16"],
            "alert_confidence": ["medium"],
            "area_ha": [1.0],
        },
        {"aoi_id": ["BRA.16"], "area_ha": [1.0]},
        {
            "aoi_id": ["BRA.16"],
            "alert_confidence": ["high"],
            "area_ha": ["lots"],
        },
        {
            "aoi_id": ["BRA.16", "BRA.16"],
            "alert_confidence": ["high"],
            "area_ha": [1.0, 2.0],
        },
    ],
    ids=[
        "unknown-tier",
        "no-confidence-column",
        "non-numeric-area",
        "uneven-columns",
    ],
)
async def test_summarize_reports_an_unreadable_result_as_unavailable(data):
    parana = uuid4()

    report = await _service(_analytics_source(data)).summarize(
        {parana: PARANA}, *WEEK
    )

    assert report.dashboards == {parana: dashboard_alerts.unavailable()}


@pytest.mark.asyncio
async def test_analytics_source_raises_when_pull_fails():
    handler = FakeHandler(
        DataPullResult(success=False, data=None, message="timed out")
    )

    with pytest.raises(AlertsUnavailableError, match="timed out"):
        await AnalyticsAlertsSource(handler, BASE_URL).area_ha_by_src_id(
            [dict(PARANA)], *WEEK
        )


@pytest.mark.asyncio
async def test_analytics_source_reads_and_caches_the_latest_alert_date():
    source, requests = _latest_source(
        lambda request: httpx.Response(
            200,
            json={
                "data": {"alert_date": "2026-10-11", "version": "v20261014"},
                "status": "success",
            },
        )
    )

    assert await source.latest_alert_date() == date(2026, 10, 11)
    assert await source.latest_alert_date() == date(2026, 10, 11)

    assert [str(request.url) for request in requests] == [LATEST_URL]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503, json={"detail": "No integrated alerts dates"}),
        httpx.Response(200, json={"data": {}}),
        httpx.Response(200, text="not json"),
    ],
    ids=["error-status", "missing-date", "not-json"],
)
async def test_analytics_source_raises_without_a_latest_alert_date(response):
    source, requests = _latest_source(lambda request: response)

    with pytest.raises(AlertsUnavailableError):
        await source.latest_alert_date()
    # A failure is not cached.
    with pytest.raises(AlertsUnavailableError):
        await source.latest_alert_date()
    assert len(requests) == 2
