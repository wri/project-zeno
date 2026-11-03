"""A user's dashboards and their integrated alerts, resolved with the same
access rules the dashboard routes apply."""

from dataclasses import dataclass
from datetime import date
from typing import Optional
from uuid import UUID

from src.agent.datasets.handlers.analytics_handler import INTEGRATED_ALERTS_ID
from src.api.repositories import dashboard_writer
from src.api.services.dashboard_alerts import (
    AlertsReport,
    DashboardAlertsService,
)
from src.api.services.dashboard_aoi import dashboard_aoi


@dataclass(frozen=True)
class DashboardSummary:
    id: UUID
    name: str
    areas: list[str]
    tracks_alerts: bool


async def list_user_dashboards(user_id: str) -> list[DashboardSummary]:
    owned = await dashboard_writer.get_owned_dashboards(user_id)
    tracked = await dashboard_writer.get_visible_dashboards_with_dataset(
        [row.id for row in owned], user_id, INTEGRATED_ALERTS_ID
    )
    tracked_ids = {row.id for row in tracked}
    return [
        DashboardSummary(
            id=row.id,
            name=row.name,
            areas=[aoi.name for aoi in sorted(row.aois, key=_position)],
            tracks_alerts=row.id in tracked_ids,
        )
        for row in owned
    ]


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


def _position(aoi) -> int:
    return aoi.position
