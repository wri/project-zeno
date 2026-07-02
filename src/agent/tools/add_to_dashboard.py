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

import structlog
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from sqlalchemy import select

from src.agent.tool_spec import ToolCategory, ToolSpec
from src.api.data_models import InsightOrm
from src.api.repositories import dashboard_writer
from src.api.repositories.dashboard_access import is_editable_by_user
from src.api.repositories.insight_access import is_visible_to_user
from src.shared.database import get_session_from_pool
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


def _error_command(message: str, tool_call_id: Optional[str]) -> Command:
    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=message,
                    tool_call_id=tool_call_id,
                    status="error",
                )
            ]
        }
    )


async def _load_visible_insight(insight_id: str) -> Optional[InsightOrm]:
    """Load an insight the current user may see (own + public rule).

    Malformed ids are treated as not found. The user id comes from the
    request-scoped logging context bound by the auth dependency.
    """
    user_id = structlog.contextvars.get_contextvars().get("user_id")
    try:
        target = UUID(insight_id)
    except (ValueError, TypeError):
        return None
    async with get_session_from_pool() as session:
        result = await session.execute(
            select(InsightOrm).where(InsightOrm.id == target)
        )
        row = result.scalar_one_or_none()
    if row is None or not is_visible_to_user(row, user_id):
        return None
    return row


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
    user_id = structlog.contextvars.get_contextvars().get("user_id")

    target_insight = insight_id or state.get("insight_id")
    if not target_insight:
        return _error_command(
            "No insight to add. Generate or recall an insight first, or "
            "pass an insight_id.",
            tool_call_id,
        )

    view = state.get("view_context") or {}
    target_dashboard = (
        dashboard_id or state.get("dashboard_id") or view.get("dashboard_id")
    )
    if not target_dashboard:
        return _error_command(
            "No dashboard to add to. Create one with create_dashboard, or "
            "pass a dashboard_id.",
            tool_call_id,
        )

    logger.info(
        "add_to_dashboard tool called",
        insight_id=str(target_insight),
        dashboard_id=str(target_dashboard),
    )

    dashboard = await dashboard_writer.get_dashboard(str(target_dashboard))
    if dashboard is None or not is_editable_by_user(dashboard, user_id):
        return _error_command(
            f"Dashboard {target_dashboard} not found or not editable.",
            tool_call_id,
        )

    insight = await _load_visible_insight(str(target_insight))
    if insight is None:
        return _error_command(
            f"Insight {target_insight} not found or not accessible.",
            tool_call_id,
        )

    widget_id = await dashboard_writer.add_widget(
        str(target_dashboard),
        widget_type="insight",
        insight_id=str(target_insight),
    )
    if widget_id is None:
        return _error_command(
            f"Dashboard {target_dashboard} disappeared before the insight "
            "could be added.",
            tool_call_id,
        )

    summary = (insight.insight_text or "").strip()
    if len(summary) > 200:
        summary = summary[:200] + "…"
    return Command(
        update={
            "dashboard_id": str(dashboard.id),
            "messages": [
                ToolMessage(
                    content=(
                        f"Added insight {target_insight} to dashboard "
                        f"'{dashboard.name}' ({dashboard.id}).\n"
                        f"Insight: {summary}"
                    ),
                    tool_call_id=tool_call_id,
                    status="success",
                    # The dashboard changed on disk: the frontend re-fetches
                    # /api/dashboards/{id} on this signal.
                    response_metadata={
                        "msg_type": "dashboard_updated",
                        "dashboard_id": str(dashboard.id),
                    },
                )
            ],
        },
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
