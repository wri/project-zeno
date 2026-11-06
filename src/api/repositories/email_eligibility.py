"""Whether a dashboard can have email alerts: it needs an integrated alerts
chart and a GADM admin area, the same rule as the weekly alerts summary."""

from uuid import UUID

from src.agent.datasets.handlers.analytics_handler import INTEGRATED_ALERTS_ID
from src.api.repositories import dashboard_writer
from src.api.services.dashboard_alerts import supports_alerts
from src.api.services.dashboard_aoi import dashboard_aoi
from src.api.services.subscription import EmailEligibility


class DashboardEmailEligibility(EmailEligibility):
    async def allows_email(self, dashboard_id: UUID) -> bool:
        dashboard = await dashboard_writer.get_dashboard(dashboard_id)
        if dashboard is None:
            return False
        aoi = dashboard_aoi(dashboard)
        if aoi is None or not supports_alerts(aoi):
            return False
        with_chart = (
            await dashboard_writer.get_visible_dashboards_with_dataset(
                [dashboard.id], dashboard.user_id, INTEGRATED_ALERTS_ID
            )
        )
        return bool(with_chart)
