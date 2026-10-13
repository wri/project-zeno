from datetime import date
from uuid import uuid4

import pytest

from src.agent.datasets.handlers.analytics_handler import INTEGRATED_ALERTS_ID
from src.agent.datasets.handlers.base import DataPullResult, DataSourceHandler
from src.api.services.dashboard_alerts import (
    AlertAreaUnavailableError,
    AlertsReport,
    AnalyticsAlertAreaSource,
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
MONDAY = date(2026, 10, 12)


class FakeAlertAreaSource:
    def __init__(self, area_ha=0.0, failing=()):
        self.area_ha_value = area_ha
        self.failing = failing
        self.calls = []

    async def area_ha(self, aoi, start, end):
        self.calls.append((aoi, start, end))
        if aoi["src_id"] in self.failing:
            raise AlertAreaUnavailableError("timed out")
        return self.area_ha_value


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


@pytest.mark.parametrize(
    "today, expected",
    [
        (MONDAY, (date(2026, 10, 4), date(2026, 10, 10))),
        (date(2026, 10, 11), (date(2026, 10, 4), date(2026, 10, 10))),
        (date(2026, 10, 10), (date(2026, 9, 27), date(2026, 10, 3))),
    ],
    ids=["monday", "sunday", "saturday-week-not-over"],
)
def test_latest_alert_week_ends_on_last_full_saturday(today, expected):
    assert latest_alert_week(today) == expected


def _dashboard(aoi=PARANA, dataset_ids=(INTEGRATED_ALERTS_ID,)):
    return DashboardAlertsInput(
        dashboard_id=uuid4(), aoi=aoi, chart_dataset_ids=list(dataset_ids)
    )


@pytest.mark.asyncio
async def test_summarize_reports_area_for_latest_week():
    source = FakeAlertAreaSource(area_ha=12.5)
    service = DashboardAlertsService(source, today=lambda: MONDAY)
    dashboard = _dashboard()

    report = await service.summarize([dashboard])

    assert report == AlertsReport(
        week_start=date(2026, 10, 4),
        week_end=date(2026, 10, 10),
        dashboards={
            dashboard.dashboard_id: DashboardAlerts(integrated_alerts=12.5)
        },
    )
    assert source.calls == [(PARANA, date(2026, 10, 4), date(2026, 10, 10))]


@pytest.mark.asyncio
async def test_summarize_fetches_a_shared_area_once():
    source = FakeAlertAreaSource(area_ha=3.0)
    service = DashboardAlertsService(source, today=lambda: MONDAY)
    first, second = _dashboard(), _dashboard()

    report = await service.summarize([first, second])

    assert len(source.calls) == 1
    assert set(report.dashboards) == {first.dashboard_id, second.dashboard_id}


@pytest.mark.asyncio
async def test_summarize_reports_a_failed_area_only_on_its_dashboard():
    brazil = {**PARANA, "src_id": "BRA", "subtype": "country"}
    source = FakeAlertAreaSource(area_ha=3.0, failing={"BRA"})
    service = DashboardAlertsService(source, today=lambda: MONDAY)
    ok, failed = _dashboard(), _dashboard(aoi=brazil)

    report = await service.summarize([ok, failed])

    assert report.dashboards[ok.dashboard_id] == DashboardAlerts(
        integrated_alerts=3.0
    )
    assert report.dashboards[failed.dashboard_id] == DashboardAlerts(
        integrated_alerts=None,
        errors={"integrated_alerts": "Integrated alerts data is unavailable"},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "aoi, dataset_ids",
    [
        (PARANA, [4]),
        (None, [INTEGRATED_ALERTS_ID]),
        (
            {**PARANA, "source": "custom", "subtype": "custom-area"},
            [INTEGRATED_ALERTS_ID],
        ),
        ({**PARANA, "subtype": "municipality"}, [INTEGRATED_ALERTS_ID]),
    ],
    ids=["no-alerts-chart", "no-area", "custom-area", "unsupported-level"],
)
async def test_summarize_leaves_out_ineligible_dashboards(aoi, dataset_ids):
    source = FakeAlertAreaSource()
    service = DashboardAlertsService(source, today=lambda: MONDAY)

    report = await service.summarize([_dashboard(aoi, dataset_ids)])

    assert report.dashboards == {}
    assert source.calls == []


@pytest.mark.asyncio
async def test_analytics_source_sums_area_for_the_week():
    handler = FakeHandler(
        DataPullResult(
            success=True,
            data={
                "alert_date": ["2026-10-04", "2026-10-09"],
                "area_ha": [1.25, 2.5],
            },
            message="",
        )
    )
    source = AnalyticsAlertAreaSource(handler)

    area = await source.area_ha(PARANA, date(2026, 10, 4), date(2026, 10, 10))

    assert area == 3.75
    assert handler.last_call == {
        "dataset": {"dataset_id": INTEGRATED_ALERTS_ID},
        "start_date": "2026-10-04",
        "end_date": "2026-10-10",
        "aois": [PARANA],
    }


@pytest.mark.asyncio
async def test_analytics_source_with_no_alerts_is_zero():
    handler = FakeHandler(DataPullResult(success=True, data={}, message=""))

    area = await AnalyticsAlertAreaSource(handler).area_ha(
        PARANA, date(2026, 10, 4), date(2026, 10, 10)
    )

    assert area == 0.0


@pytest.mark.asyncio
async def test_analytics_source_raises_when_pull_fails():
    handler = FakeHandler(
        DataPullResult(success=False, data=None, message="timed out")
    )

    with pytest.raises(AlertAreaUnavailableError, match="timed out"):
        await AnalyticsAlertAreaSource(handler).area_ha(
            PARANA, date(2026, 10, 4), date(2026, 10, 10)
        )


@pytest.mark.asyncio
async def test_analytics_source_leaves_the_area_unchanged():
    class SuffixStrippingHandler(FakeHandler):
        async def pull_data(self, *args, aois, **kwargs):
            aois[0]["src_id"] = aois[0]["src_id"][:-2]
            return await super().pull_data(*args, aois=aois, **kwargs)

    handler = SuffixStrippingHandler(
        DataPullResult(success=True, data={}, message="")
    )
    aoi = dict(PARANA)

    await AnalyticsAlertAreaSource(handler).area_ha(
        aoi, date(2026, 10, 4), date(2026, 10, 10)
    )

    assert aoi == PARANA
