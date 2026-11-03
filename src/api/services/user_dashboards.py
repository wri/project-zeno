"""Integrated alerts on a user's dashboards, resolved with the same access
rules the dashboard routes apply."""

from dataclasses import dataclass
from datetime import date
from typing import Optional
from uuid import UUID

from src.agent.datasets.handlers.analytics_handler import INTEGRATED_ALERTS_ID
from src.api.repositories import dashboard_writer
from src.api.services.dashboard_alerts import (
    AlertsReport,
    DashboardAlerts,
    DashboardAlertsService,
)
from src.api.services.dashboard_aoi import dashboard_aoi


@dataclass(frozen=True)
class DashboardAlertsEntry:
    name: str
    tracks_alerts: bool
    # None when the dashboard does not track alerts or its area has none.
    alerts: Optional[DashboardAlerts]


@dataclass(frozen=True)
class UserAlertsReport:
    start_date: date
    end_date: date
    dashboards: list[DashboardAlertsEntry]


async def summarize_dashboard_alerts(
    service: DashboardAlertsService,
    user_id: str,
    dashboard_ids: list[UUID],
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> AlertsReport:
    """Alerts for the requested dashboards the user may see that have an
    integrated alerts chart; the others are left out."""
    rows = await dashboard_writer.get_visible_dashboards_with_dataset(
        dashboard_ids, user_id, INTEGRATED_ALERTS_ID
    )
    return await service.summarize(
        {row.id: dashboard_aoi(row) for row in rows}, start, end
    )


async def summarize_user_dashboard_alerts(
    service: DashboardAlertsService,
    user_id: str,
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> UserAlertsReport:
    """Alerts on every dashboard the user owns, including the ones that do
    not track them."""
    owned = await dashboard_writer.get_owned_dashboards(user_id)
    tracked = await dashboard_writer.get_visible_dashboards_with_dataset(
        [row.id for row in owned], user_id, INTEGRATED_ALERTS_ID
    )
    tracked_ids = {row.id for row in tracked}
    report = await service.summarize(
        {row.id: dashboard_aoi(row) for row in tracked}, start, end
    )
    return UserAlertsReport(
        start_date=report.start_date,
        end_date=report.end_date,
        dashboards=[
            DashboardAlertsEntry(
                name=row.name,
                tracks_alerts=row.id in tracked_ids,
                alerts=report.dashboards.get(row.id),
            )
            for row in owned
        ],
    )
