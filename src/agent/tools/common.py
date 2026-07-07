"""Shared vocabulary for the persistence-backed agent tools.

Every dashboard/insight tool speaks the same three dialects:

- request context: who the user is (``current_user_id``) and which dashboard
  a tool should target when none is named (``resolve_dashboard_id``,
  ``load_editable_dashboard``);
- error replies: a single error ToolMessage (``error_command``);
- success replies that mutate a persisted artifact: Commands that pin the
  artifact in state and tell the frontend to re-fetch it
  (``dashboard_updated_command``, ``insight_updated_command``).

Keeping these here makes each tool body a short, declarative sequence of
resolve → check → write → reply steps.
"""

from typing import Optional

from langchain_core.messages import ToolMessage
from langgraph.types import Command

from src.agent.subagents.analyst.charts.model import Insight
from src.api.data_models import DashboardOrm
from src.api.repositories import dashboard_writer
from src.api.repositories.dashboard_access import is_editable_by_user
from src.shared.request_context import current_user_id as current_user_id


def error_command(message: str, tool_call_id: Optional[str]) -> Command:
    """A Command carrying a single error ToolMessage back to the model."""
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


def resolve_dashboard_id(
    state: dict, explicit: Optional[str]
) -> Optional[str]:
    """The dashboard a tool should target, by precedence: the explicit
    argument, the dashboard touched earlier this thread (state), then the
    one the user is looking at (view_context)."""
    view = state.get("view_context") or {}
    return explicit or state.get("dashboard_id") or view.get("dashboard_id")


async def load_editable_dashboard(dashboard_id) -> Optional[DashboardOrm]:
    """Load a dashboard the current user may edit (owner-only rule);
    None when it does not exist or the user may not touch it."""
    dashboard = await dashboard_writer.get_dashboard(str(dashboard_id))
    if dashboard is None or not is_editable_by_user(
        dashboard, current_user_id()
    ):
        return None
    return dashboard


def dashboard_updated_command(
    dashboard_id, content: str, tool_call_id: Optional[str]
) -> Command:
    """Success reply for a dashboard write: pins the dashboard in state and
    signals the frontend to re-fetch /api/dashboards/{id}."""
    return Command(
        update={
            "dashboard_id": str(dashboard_id),
            "messages": [
                ToolMessage(
                    content=content,
                    tool_call_id=tool_call_id,
                    status="success",
                    response_metadata={
                        "msg_type": "dashboard_updated",
                        "dashboard_id": str(dashboard_id),
                    },
                )
            ],
        },
    )


def insight_updated_command(
    insight_id, insight: Insight, content: str, tool_call_id: Optional[str]
) -> Command:
    """Success reply for an existing insight put (back) on screen: pushes the
    insight into state in the shape `generate_insights` uses and signals the
    frontend to re-fetch /api/insights/{id} (replace in place, not a new
    card — distinct from the "human_feedback" msg_type of new insights)."""
    return Command(
        update={
            "insight_id": str(insight_id),
            "insight": insight.primary_insight,
            "follow_up_suggestions": insight.follow_up_suggestions,
            "charts_data": [c.to_frontend_dict() for c in insight.charts],
            "messages": [
                ToolMessage(
                    content=content,
                    tool_call_id=tool_call_id,
                    status="success",
                    response_metadata={
                        "msg_type": "insight_updated",
                        "insight_id": str(insight_id),
                    },
                )
            ],
        },
    )
