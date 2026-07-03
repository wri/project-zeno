"""inspect_view_context — surface the user's current frontend view state.

The frontend sends an ambient "view state" snapshot (which page the user is
on, the map viewport, which layers/AOIs/insights are visible) with each chat
request. It is stored on AgentState (``view_context``) but deliberately kept
out of the prompt — only a one-line breadcrumb appears in the session block.
This tool returns the full snapshot when the agent actually needs it to answer
a query that refers to what the user is looking at.

Insights are the exception to "just echo what the frontend sent": they carry a
lot of content that lives in the database, not the snapshot. When the frontend
reports visible insight ids (typically on the report page), the tool loads each
insight and prints its most important content — summary, chart titles and the
variables behind each chart — so the agent can reason about what's on screen
even when that detail isn't already in the conversation history.
"""

import json
from typing import Annotated, Dict, Optional
from uuid import UUID

import structlog
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.agent.tool_spec import ToolCategory, ToolSpec
from src.api.data_models import DashboardOrm, InsightOrm
from src.api.repositories import dashboard_writer
from src.api.repositories.dashboard_access import (
    is_visible_to_user as dashboard_is_visible_to_user,
)
from src.api.repositories.insight_access import is_visible_to_user
from src.shared.database import get_session_from_pool
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

# view_context keys the tool understands explicitly; everything else is dumped
# verbatim under "Other" so nothing the frontend sends is silently lost.
_KNOWN_KEYS = {
    "page",
    "viewport",
    "visible_layers",
    "visible_aois",
    "visible_insights",
    "dashboard_id",
    "dashboard_name",
}


def _label(item: object, *keys: str) -> str:
    """Best human-readable label for a layer/AOI entry, always a string."""
    if isinstance(item, dict):
        for key in keys:
            value = item.get(key)
            if value:
                return str(value)
        return "?"
    return str(item)


def format_view_context(view: dict) -> str:
    """Render the well-known parts of the view-state snapshot as readable text.

    The snapshot is free-form (the frontend owns its shape); we surface the
    well-known keys explicitly and fall back to a JSON dump for the rest.
    Insights are handled separately (they are loaded from the database).
    """
    if not view:
        return (
            "No frontend view context is available — the app did not report "
            "what the user is currently looking at."
        )

    lines = ["Current frontend view:"]

    page = view.get("page")
    if page:
        lines.append(f"- Page: {page}")

    viewport = view.get("viewport")
    if viewport:
        bbox = viewport.get("bbox") if isinstance(viewport, dict) else None
        zoom = viewport.get("zoom") if isinstance(viewport, dict) else None
        parts = []
        if bbox:
            parts.append(f"bbox {bbox}")
        if zoom is not None:
            parts.append(f"zoom {zoom}")
        lines.append(f"- Viewport: {', '.join(parts) if parts else viewport}")

    layers = view.get("visible_layers")
    if layers:
        names = [_label(layer, "name", "id") for layer in layers]
        lines.append(f"- Visible layers ({len(names)}): {', '.join(names)}")

    aois = view.get("visible_aois")
    if aois:
        names = [_label(aoi, "name", "src_id") for aoi in aois]
        lines.append(f"- Visible AOIs ({len(names)}): {', '.join(names)}")

    insights = view.get("visible_insights")
    if insights:
        # Detail is loaded from the DB and appended by the tool; here we just
        # note the count so the line shows even if a load later turns up empty.
        lines.append(f"- Visible insights: {len(insights)} (detail below)")

    if view.get("dashboard_id"):
        # Same deal: the dashboard content is loaded from the DB by the tool.
        lines.append(
            f"- Dashboard being viewed: {view['dashboard_id']} (detail below)"
        )

    # Surface any other keys the frontend sent so nothing is lost.
    extra = {k: v for k, v in view.items() if k not in _KNOWN_KEYS}
    if extra:
        lines.append(f"- Other: {json.dumps(extra, default=str)}")

    return "\n".join(lines)


def _extract_insight_ids(refs: object) -> list[UUID]:
    """Parse insight ids out of view_context['visible_insights'].

    Entries may be ``{"id": ...}`` dicts or bare id strings. Unparseable
    values are skipped rather than failing the whole call.
    """
    if not isinstance(refs, list):
        return []
    ids: list[UUID] = []
    for ref in refs:
        raw = ref.get("id") if isinstance(ref, dict) else ref
        if not raw:
            continue
        try:
            ids.append(UUID(str(raw)))
        except (ValueError, TypeError):
            logger.warning("inspect_view_context: bad insight id %r", raw)
    return ids


async def _load_insights(insight_ids: list[UUID]) -> list[InsightOrm]:
    """Load insights (with charts) the current user is allowed to see.

    Visibility is the shared `insight_access` rule (own + public). The user id
    comes from the request-scoped logging context bound by the auth dependency.
    """
    if not insight_ids:
        return []
    user_id = structlog.contextvars.get_contextvars().get("user_id")
    async with get_session_from_pool() as session:
        result = await session.execute(
            select(InsightOrm)
            .options(selectinload(InsightOrm.charts))
            .where(InsightOrm.id.in_(insight_ids))
        )
        rows = result.scalars().all()
    return [row for row in rows if is_visible_to_user(row, user_id)]


def _chart_variables(chart) -> str:
    """Summarize the fields (variables) a chart is built from."""
    parts = []
    if chart.x_axis:
        parts.append(f"x={chart.x_axis}")
    if chart.y_axis:
        parts.append(f"y={chart.y_axis}")
    if chart.color_field:
        parts.append(f"color={chart.color_field}")
    if chart.stack_field:
        parts.append(f"stack={chart.stack_field}")
    if chart.group_field:
        parts.append(f"group={chart.group_field}")
    if chart.series_fields:
        parts.append(f"series={', '.join(chart.series_fields)}")
    return ", ".join(parts) if parts else "no variables"


def format_insights(rows: list[InsightOrm]) -> str:
    """Render the most important content of each on-screen insight.

    Prints the summary, each chart's title + variables and the follow-up
    suggestions. The raw chart data rows are deliberately omitted (only the
    row count) to keep the message focused and cheap.
    """
    lines = ["Insights on screen:"]
    for row in rows:
        created = (
            row.created_at.strftime("%Y-%m-%d") if row.created_at else "?"
        )
        lines.append(f"\nInsight {row.id} (created {created}):")
        if row.insight_text:
            lines.append(f"  Summary: {row.insight_text}")
        for chart in row.charts or []:
            title = chart.title or "(untitled)"
            rows_n = len(chart.chart_data or [])
            lines.append(
                f'  Chart "{title}" ({chart.chart_type}): '
                f"{_chart_variables(chart)} — {rows_n} data point(s)"
            )
        if row.follow_up_suggestions:
            lines.append(
                "  Follow-ups: " + "; ".join(row.follow_up_suggestions)
            )
    return "\n".join(lines)


async def _load_dashboard(dashboard_id) -> Optional[DashboardOrm]:
    """Load the dashboard being viewed, if the current user may see it.

    Visibility is the shared `dashboard_access` rule (own + public); rows the
    user may not see are treated the same as missing ones.
    """
    user_id = structlog.contextvars.get_contextvars().get("user_id")
    row = await dashboard_writer.get_dashboard(dashboard_id)
    if row is None or not dashboard_is_visible_to_user(row, user_id):
        return None
    return row


async def format_dashboard(dashboard: DashboardOrm) -> str:
    """Render the dashboard being viewed: name, area(s) and its widgets.

    Insight widgets are expanded with the shared `format_insights` rendering
    (visibility-filtered), so the agent can reason about what each widget
    shows; other widgets are listed by type and config.
    """
    lines = [f"Dashboard being viewed: '{dashboard.name}' ({dashboard.id})"]
    if dashboard.description:
        lines.append(f"  Description: {dashboard.description}")
    areas = ", ".join(
        f"{aoi.name} ({aoi.source}/{aoi.subtype})"
        for aoi in dashboard.aois or []
    )
    lines.append(f"  Area(s): {areas or 'none'}")

    widgets = dashboard.widgets or []
    lines.append(f"  Widgets: {len(widgets)}")
    insight_ids = [w.insight_id for w in widgets if w.insight_id]
    for widget in widgets:
        if widget.widget_type == "insight":
            continue  # detail comes from the insight rendering below
        lines.append(
            f"  Widget {widget.position} ({widget.widget_type}): "
            f"{json.dumps(widget.config or {}, default=str)}"
        )

    sections = ["\n".join(lines)]
    if insight_ids:
        rows = await _load_insights(insight_ids)
        if rows:
            sections.append(format_insights(rows))
    return "\n\n".join(sections)


@tool("inspect_view_context")
async def inspect_view_context(
    state: Annotated[Dict, InjectedState],
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Return what the user is currently looking at in the app.

    Reports the current page (map vs report vs dashboard), the map viewport,
    the layers and AOIs visible on screen, and — when the frontend reports
    visible insights (e.g. on the report page) — the key content of each
    insight: its summary, chart titles and the variables behind each chart.
    When the user is viewing a dashboard, reports its name, area(s) and
    widgets, with insight widgets expanded the same way. Call this when the
    user refers to "this", "here", the current view, the report, the
    dashboard, or an insight on screen, and you need those details to answer.
    """
    view = (state or {}).get("view_context") or {}
    logger.info(
        "inspect_view_context tool called",
        page=view.get("page"),
        has_view_context=bool(view),
    )

    sections = [format_view_context(view)]

    insight_ids = _extract_insight_ids(view.get("visible_insights"))
    if insight_ids:
        rows = await _load_insights(insight_ids)
        logger.info(
            "inspect_view_context loaded insights",
            requested=len(insight_ids),
            loaded=len(rows),
        )
        if rows:
            sections.append(format_insights(rows))
        else:
            sections.append(
                "Insights on screen: referenced but none could be loaded "
                "(not found or not accessible)."
            )

    if view.get("dashboard_id"):
        dashboard = await _load_dashboard(view["dashboard_id"])
        if dashboard is not None:
            sections.append(await format_dashboard(dashboard))
        else:
            sections.append(
                "Dashboard being viewed: referenced but could not be loaded "
                "(not found or not accessible)."
            )

    return Command(
        update={
            "messages": [
                ToolMessage(
                    "\n\n".join(sections),
                    tool_call_id=tool_call_id,
                    status="success",
                )
            ],
        },
    )


SPEC = ToolSpec(
    tool=inspect_view_context,
    category=ToolCategory.PRIMITIVE,
    prompt_fragment=(
        "- inspect_view_context(): returns what the user is currently looking "
        "at in the app (page, map viewport, visible layers, visible AOIs, the "
        "content of any insights on screen — summary, charts and variables — "
        "and, on the dashboard page, the dashboard's name, areas and "
        "widgets). Call this when the user refers to 'this', 'here', the "
        "current view, the report, the dashboard, or an insight on screen."
    ),
)
