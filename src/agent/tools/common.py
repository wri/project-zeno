"""Shared vocabulary for the persistence-backed agent tools.

Every dashboard/insight tool speaks the same three dialects:

- request context: who the user is (``current_user_id``), which dashboard
  a tool should target when none is named (``resolve_dashboard_id``,
  ``load_editable_dashboard``) and which section of it a widget belongs to
  (``resolve_section``);
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
from src.shared.logging_config import get_logger
from src.shared.request_context import current_user_id as current_user_id

logger = get_logger(__name__)


def require_current_user_id(tool_name: str) -> str:
    """The authenticated user this tool call acts as; raises when unbound.

    Every path into the agent binds an identity (the chat endpoint requires
    auth, the CLI binds a default user), so a missing user id inside a tool
    can only mean the identity channel itself broke — e.g. contextvar
    propagation lost across an async boundary. Silently degrading instead
    (searches narrowing to public rows, writes reporting "not found or not
    editable") is indistinguishable from an ordinary permission miss, so
    authorization-relevant reads in tools must come through here rather than
    calling ``current_user_id`` directly. The raise lands in the generic
    tool-error funnel, which logs it and returns a clean error to the model.
    """
    user_id = current_user_id()
    if user_id is None:
        logger.error("tool_invoked_without_identity", tool_name=tool_name)
        raise RuntimeError(
            f"{tool_name} invoked without an authenticated user id; "
            "the request identity context is not bound."
        )
    return user_id


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


def sealed_error_command(
    error: dashboard_writer.SealedSectionError, tool_call_id: Optional[str]
) -> Command:
    """Reply for a write the repository refused as read-only.

    The write paths that do not pass through ``resolve_section`` (editing a
    section, editing or moving a widget already on a dashboard) only learn
    the section is sealed when the repository raises. The reply names the
    only ways forward, so the model explains rather than retries.
    """
    return error_command(
        f"Section {error.section_id} is read-only: the "
        f"'{error.section_type}' analysis template built it in one piece. "
        "Its title, description and the content of its widgets cannot be "
        "changed, and widgets cannot be added, removed or moved in or out. "
        "Tell the user the content cannot be edited. Such a section can "
        "still be rebuilt for a different period with "
        "update_analysis_section, and its widgets rearranged and resized in "
        "the app; anything else means deleting it and building a new one.",
        tool_call_id,
    )


def resolve_dashboard_id(
    state: dict, explicit: Optional[str]
) -> Optional[str]:
    """The dashboard a tool should target, by precedence: the explicit
    argument, the dashboard touched earlier this thread (state), then the
    one the user is looking at (view_context)."""
    view = state.get("view_context") or {}
    return explicit or state.get("dashboard_id") or view.get("dashboard_id")


async def load_editable_dashboard(
    dashboard_id, tool_name: str
) -> Optional[DashboardOrm]:
    """Load a dashboard the current user may edit (owner-only rule);
    None when it does not exist or the user may not touch it."""
    dashboard = await dashboard_writer.get_dashboard(str(dashboard_id))
    if dashboard is None or not is_editable_by_user(
        dashboard, require_current_user_id(tool_name)
    ):
        return None
    return dashboard


def format_sections(dashboard: DashboardOrm) -> str:
    """One-line listing of a dashboard's sections for a tool reply, so the
    model can name one on the next call. "none" when there are no sections."""
    sections = dashboard.sections or []
    if not sections:
        return "none"
    return "; ".join(
        f"'{section.title}' ({section.id})"
        + (
            " [read-only]"
            if section.type in dashboard_writer.SEALED_SECTION_TYPES
            else ""
        )
        for section in sections
    )


def _section_or_sealed(row):
    """The matched section, or an error when a template sealed it: a sealed
    section is built in one piece and cannot take a widget the model
    adds."""
    if row.type in dashboard_writer.SEALED_SECTION_TYPES:
        return None, (
            f"Section '{row.title}' ({row.id}) is read-only — it was built "
            "in one piece and cannot take new widgets. Put the widget in "
            "another section, or leave `section` out to add it ungrouped."
        )
    return row, None


def resolve_section(dashboard: DashboardOrm, section: Optional[str]):
    """The section a widget should join, as ``(section_orm, error_message)``.

    ``section`` names one of the dashboard's sections either by id or by
    title (case-insensitive) — the model normally has the title to hand and
    the id only from an earlier tool reply. ``None`` means "ungrouped", which
    is not an error: ``(None, None)``. An unmatched name is an error that
    lists the real sections so the model can retry or create one.

    Ids are matched first and are unambiguous. Titles are not unique: the
    agent refuses to create a duplicate, but the REST API does not, so two
    sections made in the UI can share a title. Rather than silently picking
    one, an ambiguous title is an error that lists the candidate ids for the
    model to choose from.

    A sealed section (one an analysis template built in one piece) is
    refused here rather than at the write: the repository would raise
    anyway, and the model gets a reply that says what to do instead.
    """
    if not section:
        return None, None
    wanted = str(section).strip()
    rows = dashboard.sections or []
    for row in rows:
        if str(row.id) == wanted:
            return _section_or_sealed(row)
    by_title = [
        row for row in rows if row.title.casefold() == wanted.casefold()
    ]
    if len(by_title) == 1:
        return _section_or_sealed(by_title[0])
    if by_title:
        ids = ", ".join(str(row.id) for row in by_title)
        return None, (
            f"Dashboard '{dashboard.name}' has {len(by_title)} sections "
            f"titled '{by_title[0].title}'. Name the one you mean by id "
            f"instead of by title: {ids}."
        )
    return None, (
        f"Dashboard '{dashboard.name}' has no section '{section}'. "
        f"Existing sections: {format_sections(dashboard)}. Create it with "
        "add_dashboard_section, or leave the section out to add the widget "
        "ungrouped."
    )


def dashboard_updated_command(
    dashboard_id,
    dashboard_name: str,
    content: str,
    tool_call_id: Optional[str],
) -> Command:
    """Success reply for a dashboard write: pins the dashboard in state and
    signals the frontend to re-fetch /api/dashboards/{id}. The name rides
    along so the frontend can render a link to the dashboard without an
    extra fetch."""
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
                        "dashboard_name": dashboard_name,
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
