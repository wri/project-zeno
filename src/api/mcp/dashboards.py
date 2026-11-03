from datetime import date
from typing import Optional

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from src.api.mcp.users import signed_in_user
from src.api.services.dashboard_alerts import (
    DashboardAlertsService,
    InvalidPeriodError,
)
from src.api.services.user_dashboards import (
    UserAlertsReport,
    summarize_user_dashboard_alerts,
)

ALERTS = "integrated disturbance alerts"


def register(server: FastMCP, alerts: DashboardAlertsService) -> None:
    @server.tool
    async def summarize_dashboard_alerts(
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> str:
        """Area of integrated disturbance alerts (potential vegetation and
        forest disturbance, in hectares) on each of the user's dashboards
        over a period, largest first, with the total. Leave the dates out
        for the 7 days ending on the latest alert date. Only dashboards
        with an integrated alerts chart have a figure; the others are
        listed as not tracked, which does not mean zero alerts."""
        try:
            report = await summarize_user_dashboard_alerts(
                alerts, signed_in_user(), start_date, end_date
            )
        except InvalidPeriodError as error:
            raise ToolError(str(error))
        return describe_alerts(report)


def describe_alerts(report: UserAlertsReport) -> str:
    if not report.dashboards:
        return "The user has no dashboards."
    figures: list[tuple[str, float]] = []
    without_figure = []
    not_tracked = []
    for dashboard in report.dashboards:
        if not dashboard.tracks_alerts:
            not_tracked.append(dashboard.name)
        elif dashboard.alerts is None:
            without_figure.append(
                f"- {dashboard.name}: no figure, alerts are not available "
                "for this kind of area"
            )
        elif dashboard.alerts.integrated_alerts is None:
            without_figure.append(
                f"- {dashboard.name}: alerts data is unavailable"
            )
        else:
            figures.append(
                (dashboard.name, dashboard.alerts.integrated_alerts)
            )
    figures.sort(key=lambda figure: figure[1], reverse=True)
    lines = [
        f"Area of {ALERTS}, {report.start_date} to {report.end_date}, "
        "largest first:",
        *(f"- {name}: {area_ha:,.0f} ha" for name, area_ha in figures),
    ]
    if figures:
        total = sum(area_ha for _, area_ha in figures)
        label = "Total" if not without_figure else "Total of the above"
        lines.append(f"{label}: {total:,.0f} ha")
    lines.extend(without_figure)
    if not_tracked:
        lines.append(
            "Not tracked (no integrated alerts chart, so no figure; not "
            "the same as zero alerts): " + ", ".join(not_tracked)
        )
    return "\n".join(lines)
