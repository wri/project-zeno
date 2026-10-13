"""Integrated alerts area in a dashboard's area for the latest full alert
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
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

SATURDAY = 5


class AlertAreaUnavailableError(Exception):
    pass


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


class AlertAreaSource(Protocol):
    async def area_ha(self, aoi: dict, start: date, end: date) -> float: ...


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


def area_key(aoi: dict) -> tuple[str, str]:
    return aoi["source"], aoi["src_id"]


def alerts_from(result: float | BaseException) -> DashboardAlerts:
    if isinstance(result, BaseException):
        logger.warning("dashboard_alerts_unavailable", error=repr(result))
        return DashboardAlerts(
            integrated_alerts=None,
            errors={
                "integrated_alerts": "Integrated alerts data is unavailable"
            },
        )
    return DashboardAlerts(integrated_alerts=result)


class DashboardAlertsService:
    def __init__(
        self,
        source: AlertAreaSource,
        today: Callable[[], date] = date.today,
    ):
        self._source = source
        self._today = today

    async def summarize(
        self, dashboards: list[DashboardAlertsInput]
    ) -> AlertsReport:
        start, end = latest_alert_week(self._today())
        eligible = [d for d in dashboards if is_eligible(d)]
        areas = {area_key(d.aoi): d.aoi for d in eligible if d.aoi}
        results = await asyncio.gather(
            *(self._source.area_ha(aoi, start, end) for aoi in areas.values()),
            return_exceptions=True,
        )
        alerts_by_area = {
            key: alerts_from(result) for key, result in zip(areas, results)
        }
        return AlertsReport(
            week_start=start,
            week_end=end,
            dashboards={
                d.dashboard_id: alerts_by_area[area_key(d.aoi)]
                for d in eligible
                if d.aoi
            },
        )


class AnalyticsAlertAreaSource:
    def __init__(self, handler: DataSourceHandler):
        self._handler = handler

    async def area_ha(self, aoi: dict, start: date, end: date) -> float:
        result = await self._handler.pull_data(
            query="",
            dataset={"dataset_id": INTEGRATED_ALERTS_ID},
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            change_over_time_query=False,
            aois=[dict(aoi)],
        )
        if not result.success:
            raise AlertAreaUnavailableError(result.message)
        return float(sum((result.data or {}).get("area_ha", [])))
