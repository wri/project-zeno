from datetime import date
from uuid import uuid4

import httpx
import pytest

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
MONDAY = date(2026, 10, 12)
WEEK = (date(2026, 10, 4), date(2026, 10, 10))
LATEST_ALERT_DATE = date(2026, 10, 9)
LATEST_PERIOD = (date(2026, 10, 3), LATEST_ALERT_DATE)
BASE_URL = "https://analytics.example.com"
LATEST_URL = BASE_URL + "/v0/land_change/integrated_alerts/latest"


class FakeAlertsSource:
    def __init__(
        self, area_ha_by_src_id=None, fail=False, latest=LATEST_ALERT_DATE
    ):
        self.area_ha = area_ha_by_src_id or {}
        self.fail = fail
        self.latest = latest
        self.calls = []

    async def area_ha_by_src_id(self, aois, start, end):
        self.calls.append((aois, start, end))
        if self.fail:
            raise AlertsUnavailableError("timed out")
        return self.area_ha

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
        {**PARANA, "source": "custom", "subtype": "custom-area"},
        {**PARANA, "subtype": "municipality"},
    ],
    ids=["no-aoi", "custom-aoi", "unsupported-level"],
)
async def test_summarize_leaves_out_unsupported_aois(aoi):
    source = FakeAlertsSource()

    report = await _service(source).summarize({uuid4(): aoi})

    assert report.dashboards == {}
    assert source.calls == []


@pytest.mark.asyncio
async def test_analytics_source_sums_area_by_aoi():
    handler = FakeHandler(
        DataPullResult(
            success=True,
            data={
                "aoi_id": ["BRA.16", "BRA.14", "BRA.14"],
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
