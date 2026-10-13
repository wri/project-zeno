"""Integrated alerts area in a dashboard's AOI for the latest full alert
week, which runs Sunday to Saturday."""

import asyncio
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
    chart_dataset_ids: list[int]


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
        INTEGRATED_ALERTS_ID in dashboard.chart_dataset_ids
        and dashboard.aoi is not None
        and supports_alerts(dashboard.aoi)
    )


def aoi_key(aoi: dict) -> AoiKey:
    return aoi["source"], aoi["src_id"]


UNAVAILABLE = DashboardAlerts(
    integrated_alerts=None,
    errors={"integrated_alerts": "Integrated alerts data is unavailable"},
)


class DashboardAlertsService:
    def __init__(
        self,
        source: AlertsSource,
        today: Callable[[], date] = date.today,
    ):
        self._source = source
        self._today = today

    async def summarize(
        self, dashboards: list[DashboardAlertsInput]
    ) -> AlertsReport:
        start, end = latest_alert_week(self._today())
        eligible = [
            (d.dashboard_id, d.aoi)
            for d in dashboards
            if is_eligible(d) and d.aoi
        ]
        aois_by_source: dict[str, dict[AoiKey, dict]] = {}
        for _, aoi in eligible:
            aois_by_source.setdefault(aoi["source"], {})[aoi_key(aoi)] = aoi
        alerts_by_aoi: dict[AoiKey, DashboardAlerts] = {}
        for aois in await asyncio.gather(
            *(
                self._alerts(list(aois.values()), start, end)
                for aois in aois_by_source.values()
            )
        ):
            alerts_by_aoi.update(aois)
        return AlertsReport(
            week_start=start,
            week_end=end,
            dashboards={
                dashboard_id: alerts_by_aoi[aoi_key(aoi)]
                for dashboard_id, aoi in eligible
            },
        )

    async def _alerts(
        self, aois: list[dict], start: date, end: date
    ) -> dict[AoiKey, DashboardAlerts]:
        try:
            area_ha = await self._source.area_ha_by_aoi(aois, start, end)
        except Exception as error:
            logger.warning("dashboard_alerts_unavailable", error=repr(error))
            return {aoi_key(aoi): UNAVAILABLE for aoi in aois}
        return {
            aoi_key(aoi): DashboardAlerts(
                integrated_alerts=area_ha.get(aoi_key(aoi), 0.0)
            )
            for aoi in aois
        }


class AnalyticsAlertsSource:
    def __init__(self, handler: DataSourceHandler):
        self._handler = handler

    async def area_ha_by_aoi(
        self, aois: list[dict], start: date, end: date
    ) -> dict[AoiKey, float]:
        result = await self._handler.pull_data(
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
        return {
            aoi_key(aoi): area_ha_by_id[format_id(aoi["src_id"])]
            for aoi in aois
            if format_id(aoi["src_id"]) in area_ha_by_id
        }
