"""Integrated alerts area in each dashboard's AOI over a period, by default
the latest full alert week, which runs Sunday to Saturday."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Iterable, Optional, Protocol
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


class InvalidPeriodError(ValueError):
    pass


@dataclass(frozen=True)
class DashboardAlerts:
    integrated_alerts: Optional[float]
    errors: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AlertsReport:
    start_date: date
    end_date: date
    dashboards: dict[UUID, DashboardAlerts]


class AlertsSource(Protocol):
    async def area_ha_by_src_id(
        self, aois: list[dict], start: date, end: date
    ) -> dict[str, float]:
        """Alert area of each AOI that has alerts."""
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


def distinct_aois(aois: Iterable[dict]) -> list[dict]:
    return list({aoi["src_id"]: aoi for aoi in aois}.values())


def unavailable() -> DashboardAlerts:
    return DashboardAlerts(
        integrated_alerts=None,
        errors={"integrated_alerts": "Integrated alerts data is unavailable"},
    )


class DashboardAlertsService:
    def __init__(
        self,
        source: AlertsSource,
        today: Callable[[], date] = date.today,
    ):
        self.source = source
        self.today = today

    async def summarize(
        self,
        aoi_by_dashboard: dict[UUID, Optional[dict]],
        start: Optional[date] = None,
        end: Optional[date] = None,
    ) -> AlertsReport:
        """Alerts between start and end, which default to the latest full
        alert week."""
        default_start, default_end = latest_alert_week(self.today())
        start, end = start or default_start, end or default_end
        if start > end:
            raise InvalidPeriodError(f"{start} is after {end}.")
        supported = {
            dashboard_id: aoi
            for dashboard_id, aoi in aoi_by_dashboard.items()
            if aoi is not None and supports_alerts(aoi)
        }
        alerts_by_src_id = await self._alerts_by_src_id(
            distinct_aois(supported.values()), start, end
        )
        return AlertsReport(
            start_date=start,
            end_date=end,
            dashboards={
                dashboard_id: alerts_by_src_id[aoi["src_id"]]
                for dashboard_id, aoi in supported.items()
            },
        )

    async def _alerts_by_src_id(
        self, aois: list[dict], start: date, end: date
    ) -> dict[str, DashboardAlerts]:
        if not aois:
            return {}
        try:
            area_ha = await self.source.area_ha_by_src_id(aois, start, end)
        except AlertsUnavailableError as error:
            logger.warning("dashboard_alerts_unavailable", error=str(error))
            return {aoi["src_id"]: unavailable() for aoi in aois}
        return {
            aoi["src_id"]: DashboardAlerts(
                integrated_alerts=area_ha.get(aoi["src_id"], 0.0)
            )
            for aoi in aois
        }


def total_area_ha_by_aoi_id(data: dict) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for aoi_id, area_ha in zip(
        data.get("aoi_id", []), data.get("area_ha", [])
    ):
        totals[aoi_id] += area_ha
    return dict(totals)


class AnalyticsAlertsSource:
    def __init__(self, handler: DataSourceHandler):
        self.handler = handler

    async def area_ha_by_src_id(
        self, aois: list[dict], start: date, end: date
    ) -> dict[str, float]:
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
        src_id_by_aoi_id = {
            format_id(aoi["src_id"]): aoi["src_id"] for aoi in aois
        }
        return {
            src_id_by_aoi_id[aoi_id]: area_ha
            for aoi_id, area_ha in total_area_ha_by_aoi_id(
                result.data or {}
            ).items()
        }
