from datetime import date
from uuid import uuid4

import pytest

from src.agent.datasets.handlers.analytics_handler import INTEGRATED_ALERTS_ID
from src.agent.datasets.handlers.base import DataPullResult, DataSourceHandler
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


class FakeAlertsSource:
    def __init__(self, area_ha_by_src_id=None, fail=False):
        self.area_ha = area_ha_by_src_id or {}
        self.fail = fail
        self.calls = []

    async def area_ha_by_src_id(self, aois, start, end):
        self.calls.append((aois, start, end))
        if self.fail:
            raise AlertsUnavailableError("timed out")
        return self.area_ha


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

    assert source.calls == [([PARANA, PARA], *WEEK)]
    assert (report.start_date, report.end_date) == WEEK
    assert report.dashboards == {
        parana: DashboardAlerts(integrated_alerts=12.5),
        also_parana: DashboardAlerts(integrated_alerts=12.5),
        para: DashboardAlerts(integrated_alerts=0.0),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "start, end, expected",
    [
        (
            date(2026, 9, 1),
            date(2026, 9, 30),
            (date(2026, 9, 1), date(2026, 9, 30)),
        ),
        (date(2026, 9, 1), None, (date(2026, 9, 1), WEEK[1])),
    ],
    ids=["both-dates", "missing-end-uses-default"],
)
async def test_summarize_uses_the_requested_period(start, end, expected):
    source = FakeAlertsSource()

    report = await _service(source).summarize({uuid4(): PARANA}, start, end)

    assert source.calls == [([PARANA], *expected)]
    assert (report.start_date, report.end_date) == expected


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

    area_ha = await AnalyticsAlertsSource(handler).area_ha_by_src_id(
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
        await AnalyticsAlertsSource(handler).area_ha_by_src_id(
            [dict(PARANA)], *WEEK
        )
