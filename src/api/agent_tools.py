"""Dashboard tools for the agent, served by an MCP server the agent reaches
in-process. Tools act as the user of the current request."""

from contextlib import asynccontextmanager
from datetime import date
from typing import AsyncIterator, Optional
from uuid import UUID

from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.tools import load_mcp_tools

from src.api.services.dashboard_alerts import (
    AlertsReport,
    DashboardAlertsService,
    InvalidPeriodError,
)
from src.api.services.user_dashboards import (
    DashboardSummary,
    list_user_dashboards,
    summarize_dashboard_alerts,
)
from src.shared.request_context import current_user_id

ALERTS = "integrated disturbance alerts"


def dashboards_server(alerts: DashboardAlertsService) -> FastMCP:
    server = FastMCP("dashboards")

    @server.tool
    async def list_dashboards() -> str:
        """List the user's dashboards: name, id, areas, and whether each
        tracks integrated disturbance alerts."""
        dashboards = await list_user_dashboards(signed_in_user())
        if not dashboards:
            return "The user has no dashboards."
        return f"{len(dashboards)} dashboards:\n" + "\n".join(
            describe_dashboard(dashboard) for dashboard in dashboards
        )

    @server.tool(name="summarize_dashboard_alerts")
    async def summarize_alerts(
        dashboard_ids: Optional[list[UUID]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> str:
        """Area of integrated disturbance alerts (potential vegetation and
        forest disturbance, in hectares) on the user's dashboards over a
        period. Leave the dates out for the 7 days ending on the latest
        alert date, and leave dashboard_ids out to cover every dashboard.
        Only dashboards with an integrated alerts chart have a figure; the
        others are listed as not tracked, which does not mean zero
        alerts."""
        user_id = signed_in_user()
        dashboards = await list_user_dashboards(user_id)
        if dashboard_ids is not None:
            dashboards = [d for d in dashboards if d.id in dashboard_ids]
        tracked = [d for d in dashboards if d.tracks_alerts]
        try:
            report = await summarize_dashboard_alerts(
                alerts, user_id, [d.id for d in tracked], start_date, end_date
            )
        except InvalidPeriodError as error:
            raise ToolError(str(error))
        return describe_alerts(report, dashboards)

    return server


@asynccontextmanager
async def api_tools(
    alerts: DashboardAlertsService,
) -> AsyncIterator[list[BaseTool]]:
    async with Client(dashboards_server(alerts)) as client:
        yield await load_mcp_tools(client.session)


def signed_in_user() -> str:
    user_id = current_user_id()
    if not user_id:
        raise ToolError("Dashboards are only available to signed in users.")
    return user_id


def describe_dashboard(dashboard: DashboardSummary) -> str:
    tracking = "tracks" if dashboard.tracks_alerts else "does not track"
    areas = ", ".join(dashboard.areas) or "no areas"
    return (
        f"- {dashboard.name} (id {dashboard.id}): {areas}; {tracking} {ALERTS}"
    )


def describe_alerts(
    report: AlertsReport, dashboards: list[DashboardSummary]
) -> str:
    lines = [f"Area of {ALERTS}, {report.start_date} to {report.end_date}:"]
    not_tracked = []
    for dashboard in dashboards:
        alerts = report.dashboards.get(dashboard.id)
        if not dashboard.tracks_alerts:
            not_tracked.append(dashboard.name)
        elif alerts is None:
            lines.append(
                f"- {dashboard.name}: no figure, alerts are not available "
                "for this kind of area"
            )
        elif alerts.integrated_alerts is None:
            lines.append(f"- {dashboard.name}: alerts data is unavailable")
        else:
            lines.append(
                f"- {dashboard.name}: {alerts.integrated_alerts:,.0f} ha"
            )
    if not_tracked:
        lines.append(
            "Not tracked (no integrated alerts chart, so no figure; not "
            "the same as zero alerts): " + ", ".join(not_tracked)
        )
    return "\n".join(lines)
