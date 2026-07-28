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

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.agent.i18n import t
from src.agent.language import DEFAULT_LANGUAGE
from src.agent.tool_spec import ToolCategory, ToolSpec
from src.agent.tools.common import require_current_user_id
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

# Rows at or below this get full data injected; above get per-column stats.
DATA_INJECT_THRESHOLD = 30
# Meta-columns that add no signal for stats and are skipped.
DATA_SKIP_COLUMNS = {"aoi_id", "aoi_type"}
# Secondary cap on full-table output; if the formatted table exceeds this,
# fall back to stats even if row count is below the threshold.
DATA_TABLE_CHAR_LIMIT = 4000


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
    comes from the request context bound by the auth dependency.
    """
    if not insight_ids:
        return []
    user_id = require_current_user_id("inspect_view_context")
    async with get_session_from_pool() as session:
        result = await session.execute(
            select(InsightOrm)
            .options(selectinload(InsightOrm.charts))
            .where(InsightOrm.id.in_(insight_ids))
        )
        rows = result.scalars().all()
    return [row for row in rows if is_visible_to_user(row, user_id)]


async def format_numeric_stats(
    values: list, language: str = DEFAULT_LANGUAGE
) -> str:
    """Min/max/mean for a list of numeric values, ignoring None/non-numeric."""
    nums = [v for v in values if isinstance(v, (int, float)) and v is not None]
    if not nums:
        return await t("analyst.chart_data_no_numeric", language)
    mn, mx = min(nums), max(nums)
    avg = sum(nums) / len(nums)
    # If avg is a whole number, drop decimal entirely; otherwise format to 2dp
    # and strip trailing zeros (2.50 -> 2.5).
    if avg == int(avg):
        mean = str(int(avg))
    else:
        mean = f"{avg:.2f}".rstrip("0").rstrip(".")
    return await t(
        "analyst.chart_data_stats", language, min=mn, max=mx, mean=mean
    )


async def format_chart_data(chart, language: str = DEFAULT_LANGUAGE) -> str:
    """Format chart data for the agent: full rows if small, stats if large.

    For series <= DATA_INJECT_THRESHOLD: a compact text table of the rows.
    For larger series: per-column min/max/mean (numeric) or distinct count +
    samples (string).
    """
    data = chart.chart_data or []
    if not data:
        return await t("analyst.chart_data_none", language)

    rows_n = len(data)
    # Collect columns in first-seen order, skipping meta-columns.
    col_names = list(
        dict.fromkeys(
            k for row in data for k in row if k not in DATA_SKIP_COLUMNS
        )
    )
    if not col_names:
        return await t("analyst.chart_data_meta_only", language, rows=rows_n)

    if rows_n <= DATA_INJECT_THRESHOLD:
        # Small: render full table, but fall back to stats if it would be
        # too large (many columns or long values).
        header = await t(
            "analyst.chart_data_table_header",
            language,
            rows=rows_n,
            cols=len(col_names),
        )
        lines = [f"  {header}"]
        # Header.
        lines.append(f"    {''.join(f'{c:<18}' for c in col_names)}")
        for row in data:
            cells = [
                str(row.get(c, ""))[:16] if row.get(c) is not None else ""
                for c in col_names
            ]
            lines.append(f"    {''.join(f'{v:<18}' for v in cells)}")
        table_str = "\n".join(lines)
        if len(table_str) <= DATA_TABLE_CHAR_LIMIT:
            return table_str
        # Table too wide — fall through to stats.

    # Large: per-column stats.
    stats_header = await t(
        "analyst.chart_data_stats_header", language, rows=rows_n
    )
    lines = [f"  {stats_header}"]
    for col in col_names:
        values = [row.get(col) for row in data]
        nums = [
            v for v in values if isinstance(v, (int, float)) and v is not None
        ]
        if nums:
            stats = await format_numeric_stats(nums, language)
            lines.append(f"    {col}: {stats}")
        else:
            # dict.fromkeys preserves first-seen order (unlike set()), so
            # samples are stable across runs.
            distinct = list(
                dict.fromkeys(str(v) for v in values if v is not None)
            )
            samples = distinct[:4]
            samples_str = (
                ", ".join(samples) + "..." if len(distinct) > 4 else ""
            )
            distinct_str = await t(
                "analyst.chart_data_distinct",
                language,
                count=len(distinct),
                samples=samples_str,
            )
            lines.append(f"    {col}: {distinct_str}")
    return "\n".join(lines)


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


async def format_insights(
    rows: list[InsightOrm], language: str = DEFAULT_LANGUAGE
) -> str:
    """Render the most important content of each on-screen insight.

    Prints the summary, each chart's title + variables + data (full rows if
    small, per-column stats if large) and the follow-up suggestions.
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
            lines.append(await format_chart_data(chart, language))
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
    row = await dashboard_writer.get_dashboard(dashboard_id)
    if row is None or not dashboard_is_visible_to_user(
        row, require_current_user_id("inspect_view_context")
    ):
        return None
    return row


def _format_map_widget(config: dict) -> Optional[str]:
    """One-line summary of a map widget's layer snapshot, sans tile URLs.

    Returns None when the config carries neither a dataset nor an imagery
    snapshot, so the caller can fall back to a raw dump.
    """
    dataset = config.get("dataset")
    if isinstance(dataset, dict):
        line = f"map: dataset '{dataset.get('dataset_name', '?')}'"
        if dataset.get("start_date") or dataset.get("end_date"):
            line += (
                f" ({dataset.get('start_date', '?')}–"
                f"{dataset.get('end_date', '?')})"
            )
        if dataset.get("context_layer"):
            line += f", context layer {dataset['context_layer']}"
        return line
    imagery = config.get("imagery")
    if isinstance(imagery, dict):
        areas = ", ".join(imagery.get("aoi_names") or []) or "?"
        return (
            f"map: Sentinel-2 imagery around "
            f"{imagery.get('target_date', '?')} ({areas})"
        )
    return None


async def format_dashboard(dashboard: DashboardOrm) -> str:
    """Render the dashboard being viewed: name, area(s) and its widgets.

    Insight widgets are expanded with the shared `format_insights` rendering
    (visibility-filtered), so the agent can reason about what each widget
    shows; map widgets are summarized by dataset name/dates or imagery
    date/areas; anything else is listed by type and config.
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
        summary = _format_map_widget(widget.config or {})
        if summary is None:
            summary = json.dumps(widget.config or {}, default=str)
        lines.append(
            f"  Widget {widget.position} ({widget.widget_type}): {summary}"
        )

    sections = ["\n".join(lines)]
    if insight_ids:
        rows = await _load_insights(insight_ids)
        if rows:
            sections.append(await format_insights(rows))
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
            sections.append(await format_insights(rows))
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
