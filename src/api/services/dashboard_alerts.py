"""Integrated alerts area in a dashboard's AOI for the latest full alert
week, which runs Sunday to Saturday."""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Optional, Protocol
from uuid import UUID

from src.agent.datasets.handlers.analytics_handler import (
    ANALYTICS_ADMIN_SUBTYPES,
    INTEGRATED_ALERTS_ID,
)
from src.agent.datasets.handlers.base import DataSourceHandler
from src.shared.geocoding_helpers import format_id
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

SATURDAY = 5


class AlertsUnavailableError(Exception):
    pass


AoiKey = tuple[str, str]


@dataclass(frozen=True)
class DashboardAlertsInput:
    dashboard_id: UUID
    aoi: Optional[dict]
    has_alerts_chart: bool


@dataclass(frozen=True)
class DashboardAlerts:
    integrated_alerts: Optional[float]
    errors: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AlertsReport:
    week_start: date
    week_end: date
    dashboards: dict[UUID, DashboardAlerts]


class AlertsSource(Protocol):
    async def area_ha_by_aoi(
        self, aois: list[dict], start: date, end: date
    ) -> dict[AoiKey, float]:
        """Alert area for each AOI; AOIs without alerts may be absent."""
        ...


def latest_alert_week(today: date) -> tuple[date, date]:
    """The last Sunday-to-Saturday week that ended before today."""
    days_since_saturday = (today.weekday() - SATURDAY) % 7 or 7
    end = today - timedelta(days=days_since_saturday)
    return end - timedelta(days=6), end


def supports_alerts(aoi: dict) -> bool:
    return (
        aoi["source"] == "gadm" and aoi["subtype"] in ANALYTICS_ADMIN_SUBTYPES
    )


def is_eligible(dashboard: DashboardAlertsInput) -> bool:
    return (
        dashboard.has_alerts_chart
        and dashboard.aoi is not None
        and supports_alerts(dashboard.aoi)
    )


def aoi_key(aoi: dict) -> AoiKey:
    return aoi["source"], aoi["src_id"]


UNAVAILABLE = DashboardAlerts(
    integrated_alerts=None,
    errors={"integrated_alerts": "Integrated alerts data is unavailable"},
)


def aois_by_source(
    dashboards: list[DashboardAlertsInput],
) -> dict[str, list[dict]]:
    """Each source's distinct AOIs."""
    grouped: dict[str, dict[AoiKey, dict]] = {}
    for dashboard in dashboards:
        if dashboard.aoi is None:
            continue
        source_aois = grouped.setdefault(dashboard.aoi["source"], {})
        source_aois[aoi_key(dashboard.aoi)] = dashboard.aoi
    return {source: list(aois.values()) for source, aois in grouped.items()}


class DashboardAlertsService:
    def __init__(
        self,
        source: AlertsSource,
        today: Callable[[], date] = date.today,
    ):
        self.source = source
        self.today = today

    async def summarize(
        self, dashboards: list[DashboardAlertsInput]
    ) -> AlertsReport:
        start, end = latest_alert_week(self.today())
        eligible = [d for d in dashboards if is_eligible(d)]

        alerts_by_aoi: dict[AoiKey, DashboardAlerts] = {}
        for aois in aois_by_source(eligible).values():
            alerts_by_aoi.update(await self._alerts(aois, start, end))

        alerts_by_dashboard: dict[UUID, DashboardAlerts] = {}
        for dashboard in eligible:
            if dashboard.aoi is not None:
                key = aoi_key(dashboard.aoi)
                alerts_by_dashboard[dashboard.dashboard_id] = alerts_by_aoi[
                    key
                ]

        return AlertsReport(
            week_start=start, week_end=end, dashboards=alerts_by_dashboard
        )

    async def _alerts(
        self, aois: list[dict], start: date, end: date
    ) -> dict[AoiKey, DashboardAlerts]:
        try:
            area_ha = await self.source.area_ha_by_aoi(aois, start, end)
        except Exception as error:
            logger.warning("dashboard_alerts_unavailable", error=repr(error))
            return {aoi_key(aoi): UNAVAILABLE for aoi in aois}

        alerts: dict[AoiKey, DashboardAlerts] = {}
        for aoi in aois:
            key = aoi_key(aoi)
            alerts[key] = DashboardAlerts(
                integrated_alerts=area_ha.get(key, 0.0)
            )
        return alerts


class AnalyticsAlertsSource:
    def __init__(self, handler: DataSourceHandler):
        self.handler = handler

    async def area_ha_by_aoi(
        self, aois: list[dict], start: date, end: date
    ) -> dict[AoiKey, float]:
        result = await self.handler.pull_data(
            query="",
            dataset={"dataset_id": INTEGRATED_ALERTS_ID},
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            change_over_time_query=False,
            aois=[dict(aoi) for aoi in aois],
        )
        if not result.success:
            raise AlertsUnavailableError(result.message)

        data = result.data or {}
        area_ha_by_id: dict[str, float] = {}
        for aoi_id, area_ha in zip(
            data.get("aoi_id", []), data.get("area_ha", [])
        ):
            area_ha_by_id[aoi_id] = area_ha_by_id.get(aoi_id, 0.0) + area_ha

        area_ha_by_aoi: dict[AoiKey, float] = {}
        for aoi in aois:
            aoi_id = format_id(aoi["src_id"])
            if aoi_id in area_ha_by_id:
                area_ha_by_aoi[aoi_key(aoi)] = area_ha_by_id[aoi_id]
        return area_ha_by_aoi
