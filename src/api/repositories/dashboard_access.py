"""Who may see or edit a dashboard — the single place that rule lives.

Read rule: a user sees their own dashboards plus public ones.
Edit rule: only the owner may edit. Dashboards are always owned
(``user_id`` NOT NULL), but the rules tolerate owner-less rows the same way
``insight_access`` does: neither visible nor editable through the agent tools.

Both rules take the user id from the caller (the agent tools read it from the
request-scoped structlog context bound by the auth dependency) and treat a
missing user id as "not authenticated": nothing private is visible, nothing is
editable.

The API router (``src/api/routers/dashboards.py``) implements the same read
rule with two extras that don't apply to agent tools — admin/superuser
override and HTTP error semantics — so it stays separate.
"""

from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.sql.elements import ColumnElement

from src.api.data_models import (
    DashboardOrm,
    DashboardSectionOrm,
    DashboardWidgetOrm,
)
from src.shared.database import get_session_from_pool


def visible_dashboards_clause(user_id: Optional[str]) -> ColumnElement:
    """SQL WHERE clause selecting the dashboards `user_id` may see."""
    if user_id:
        return or_(
            DashboardOrm.is_public.is_(True),
            DashboardOrm.user_id == user_id,
        )
    return DashboardOrm.is_public.is_(True)


def is_visible_to_user(row: DashboardOrm, user_id: Optional[str]) -> bool:
    """Python twin of `visible_dashboards_clause` for already-loaded rows."""
    return bool(row.is_public or (user_id and row.user_id == user_id))


def is_editable_by_user(row: DashboardOrm, user_id: Optional[str]) -> bool:
    """Only the owner may edit; unauthenticated callers edit nothing."""
    return bool(user_id and row.user_id == user_id)


async def insight_is_sealed(insight_id) -> bool:
    """Whether an insight is the content of a sealed dashboard section.

    A sealed section refuses edits to its widgets, but a widget's insight is
    a row of its own: rewriting that insight's charts or narrative would
    change what the section shows without touching a single dashboard row.
    So the display-editing path asks here first.

    Errs on the side of *not* sealing: an insight on no dashboard, or on an
    ordinary section, stays editable.
    """
    # Imported here: dashboard_writer imports this module for its own rules,
    # and the seal list lives there.
    from src.api.repositories.dashboard_writer import SEALED_SECTION_TYPES

    async with get_session_from_pool() as session:
        found = await session.scalar(
            select(DashboardSectionOrm.id)
            .join(
                DashboardWidgetOrm,
                DashboardWidgetOrm.section_id == DashboardSectionOrm.id,
            )
            .where(
                DashboardWidgetOrm.insight_id == insight_id,
                DashboardSectionOrm.type.in_(SEALED_SECTION_TYPES),
            )
            .limit(1)
        )
    return found is not None
