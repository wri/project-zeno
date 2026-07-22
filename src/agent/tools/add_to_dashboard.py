"""add_to_dashboard — put an existing insight onto a dashboard as a widget.

A deterministic DB write, the second dashboard primitive next to
create_dashboard. The insight defaults to the one in state (the last one
generated or recalled this thread); the dashboard defaults to the one in
state or the one the user is looking at (view_context). Owner-only on the
dashboard; the insight must be visible to the user (own or public) — the
same access rules the API applies.
"""

from typing import Annotated, Dict, Optional
from uuid import UUID

from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from sqlalchemy import select

from src.agent.tool_spec import ToolCategory, ToolSpec
from src.agent.tools.common import (
    dashboard_updated_command,
    error_command,
    load_editable_dashboard,
    require_current_user_id,
    resolve_dashboard_id,
)
from src.api.data_models import InsightOrm
from src.api.repositories import dashboard_writer
from src.api.repositories.insight_access import is_visible_to_user
from src.shared.database import get_session_from_pool
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


async def _load_visible_insight(insight_id: str) -> Optional[InsightOrm]:
    """Load an insight the current user may see (own + public rule).

    Malformed ids are treated as not found.
    """
    try:
        target = UUID(insight_id)
    except (ValueError, TypeError):
        return None
    async with get_session_from_pool() as session:
        result = await session.execute(
            select(InsightOrm).where(InsightOrm.id == target)
        )
        row = result.scalar_one_or_none()
    if row is None or not is_visible_to_user(
        row, require_current_user_id("add_to_dashboard")
    ):
        return None
    return row


def _insight_summary(insight: InsightOrm, max_chars: int = 200) -> str:
    summary = (insight.insight_text or "").strip()
    if len(summary) > max_chars:
        summary = summary[:max_chars] + "…"
    return summary


@tool("add_to_dashboard")
async def add_to_dashboard(
    insight_id: Optional[str] = None,
    dashboard_id: Optional[str] = None,
    state: Annotated[Dict, InjectedState] | None = None,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Add an insight to a dashboard as a widget.

    Defaults: `insight_id` to the current insight in state (the last one
    generated or recalled this conversation); `dashboard_id` to the dashboard
    in state or the one the user is currently viewing. Pass explicit ids to
    target others. Only dashboards the user owns can be edited; the insight
    must be one they can see.
    """
    state = state or {}

    target_insight = insight_id or state.get("insight_id")
    if not target_insight:
        return error_command(
            "No insight to add. Generate or recall an insight first, or "
            "pass an insight_id.",
            tool_call_id,
        )

    target_dashboard = resolve_dashboard_id(state, dashboard_id)
    if not target_dashboard:
        return error_command(
            "No dashboard to add to. Create one with create_dashboard, or "
            "pass a dashboard_id.",
            tool_call_id,
        )

    logger.info(
        "add_to_dashboard tool called",
        insight_id=str(target_insight),
        dashboard_id=str(target_dashboard),
    )

    dashboard = await load_editable_dashboard(
        target_dashboard, "add_to_dashboard"
    )
    if dashboard is None:
        return error_command(
            f"Dashboard {target_dashboard} not found or not editable.",
            tool_call_id,
        )

    insight = await _load_visible_insight(str(target_insight))
    if insight is None:
        return error_command(
            f"Insight {target_insight} not found or not accessible.",
            tool_call_id,
        )

    try:
        widget_id = await dashboard_writer.add_widget(
            str(target_dashboard),
            widget_type="insight",
            insight_id=str(target_insight),
        )
    except dashboard_writer.DuplicateInsightWidgetError:
        return error_command(
            f"Insight {target_insight} is already on dashboard "
            f"'{dashboard.name}' ({dashboard.id}) — nothing to add. Tell "
            "the user it is already there; do not retry.",
            tool_call_id,
        )
    if widget_id is None:
        return error_command(
            f"Dashboard {target_dashboard} disappeared before the insight "
            "could be added.",
            tool_call_id,
        )

    return dashboard_updated_command(
        dashboard.id,
        dashboard.name,
        (
            f"Added insight {target_insight} to dashboard "
            f"'{dashboard.name}' ({dashboard.id}).\n"
            f"Insight: {_insight_summary(insight)}"
        ),
        tool_call_id,
    )


SPEC = ToolSpec(
    tool=add_to_dashboard,
    category=ToolCategory.PRIMITIVE,
    prompt_fragment=(
        "- add_to_dashboard(insight_id?, dashboard_id?): add an insight to a "
        "dashboard as a widget. Defaults to the current insight in state and "
        "the dashboard in state or on screen. Use when the user asks to add "
        "an analysis/insight to their dashboard."
    ),
)
