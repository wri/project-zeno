from datetime import date
from uuid import uuid4

import pytest

from src.agent.datasets.handlers.analytics_handler import INTEGRATED_ALERTS_ID
from src.agent.datasets.handlers.base import DataPullResult, DataSourceHandler
from src.api.services.dashboard_alerts import (
    AlertsReport,
    AlertsUnavailableError,
    AnalyticsAlertsSource,
    DashboardAlerts,
    DashboardAlertsInput,
    DashboardAlertsService,
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
        self.area_ha_by_src_id = area_ha_by_src_id or {}
        self.fail = fail
        self.calls = []

    async def area_ha_by_aoi(self, aois, start, end):
        self.calls.append((aois, start, end))
        if self.fail:
            raise AlertsUnavailableError("timed out")
        return {
            (aoi["source"], aoi["src_id"]): self.area_ha_by_src_id[
                aoi["src_id"]
            ]
            for aoi in aois
            if aoi["src_id"] in self.area_ha_by_src_id
        }


class FakeHandler(DataSourceHandler):
    def __init__(self, result: DataPullResult):
        self._result = result
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
            "aois": aois,
        }
        return self._result


def _dashboard(aoi=PARANA, has_alerts_chart=True):
    return DashboardAlertsInput(
        dashboard_id=uuid4(), aoi=aoi, has_alerts_chart=has_alerts_chart
    )


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
async def test_summarize_reports_each_aoi_from_one_request():
    source = FakeAlertsSource({"BRA.16_1": 12.5, "BRA.14_1": 3.0})
    parana, para = _dashboard(PARANA), _dashboard(PARA)

    report = await _service(source).summarize([parana, para])

    assert report == AlertsReport(
        week_start=WEEK[0],
        week_end=WEEK[1],
        dashboards={
            parana.dashboard_id: DashboardAlerts(integrated_alerts=12.5),
            para.dashboard_id: DashboardAlerts(integrated_alerts=3.0),
        },
    )
    assert source.calls == [([PARANA, PARA], *WEEK)]


@pytest.mark.asyncio
async def test_summarize_requests_a_shared_aoi_once():
    source = FakeAlertsSource({"BRA.16_1": 3.0})
    first, second = _dashboard(), _dashboard()

    report = await _service(source).summarize([first, second])

    assert source.calls == [([PARANA], *WEEK)]
    assert set(report.dashboards) == {first.dashboard_id, second.dashboard_id}


@pytest.mark.asyncio
async def test_summarize_reports_zero_for_an_aoi_without_alerts():
    dashboard = _dashboard()

    report = await _service(FakeAlertsSource()).summarize([dashboard])

    assert report.dashboards[dashboard.dashboard_id] == DashboardAlerts(
        integrated_alerts=0.0
    )


@pytest.mark.asyncio
async def test_summarize_reports_a_failed_request_on_every_dashboard_in_it():
    parana, para = _dashboard(PARANA), _dashboard(PARA)

    report = await _service(FakeAlertsSource(fail=True)).summarize(
        [parana, para]
    )

    failed = DashboardAlerts(
        integrated_alerts=None,
        errors={"integrated_alerts": "Integrated alerts data is unavailable"},
    )
    assert report.dashboards == {
        parana.dashboard_id: failed,
        para.dashboard_id: failed,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "aoi, has_alerts_chart",
    [
        (PARANA, False),
        (None, True),
        ({**PARANA, "source": "custom", "subtype": "custom-area"}, True),
        ({**PARANA, "subtype": "municipality"}, True),
    ],
    ids=["no-alerts-chart", "no-aoi", "custom-aoi", "unsupported-level"],
)
async def test_summarize_leaves_out_ineligible_dashboards(
    aoi, has_alerts_chart
):
    source = FakeAlertsSource()

    report = await _service(source).summarize(
        [_dashboard(aoi, has_alerts_chart)]
    )

    assert report.dashboards == {}
    assert source.calls == []


@pytest.mark.asyncio
async def test_analytics_source_sums_area_per_aoi_in_one_request():
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

    area_ha = await AnalyticsAlertsSource(handler).area_ha_by_aoi(
        [PARANA, PARA], *WEEK
    )

    assert area_ha == {("gadm", "BRA.16_1"): 1.25, ("gadm", "BRA.14_1"): 3.0}
    assert handler.last_call == {
        "dataset": {"dataset_id": INTEGRATED_ALERTS_ID},
        "start_date": "2026-10-04",
        "end_date": "2026-10-10",
        "aois": [PARANA, PARA],
    }


@pytest.mark.asyncio
async def test_analytics_source_with_no_alerts_is_empty():
    handler = FakeHandler(DataPullResult(success=True, data={}, message=""))

    area_ha = await AnalyticsAlertsSource(handler).area_ha_by_aoi(
        [PARANA], *WEEK
    )

    assert area_ha == {}


@pytest.mark.asyncio
async def test_analytics_source_raises_when_pull_fails():
    handler = FakeHandler(
        DataPullResult(success=False, data=None, message="timed out")
    )

    with pytest.raises(AlertsUnavailableError, match="timed out"):
        await AnalyticsAlertsSource(handler).area_ha_by_aoi([PARANA], *WEEK)


@pytest.mark.asyncio
async def test_analytics_source_leaves_the_aois_unchanged():
    class SuffixStrippingHandler(FakeHandler):
        async def pull_data(self, *args, aois, **kwargs):
            for aoi in aois:
                aoi["src_id"] = aoi["src_id"][:-2]
            return await super().pull_data(*args, aois=aois, **kwargs)

    handler = SuffixStrippingHandler(
        DataPullResult(
            success=True,
            data={"aoi_id": ["BRA.16"], "area_ha": [1.0]},
            message="",
        )
    )
    aoi = dict(PARANA)

    area_ha = await AnalyticsAlertsSource(handler).area_ha_by_aoi([aoi], *WEEK)

    assert aoi == PARANA
    assert area_ha == {("gadm", "BRA.16_1"): 1.0}
