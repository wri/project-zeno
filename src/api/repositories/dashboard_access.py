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

from sqlalchemy import or_
from sqlalchemy.sql.elements import ColumnElement

from src.api.data_models import DashboardOrm


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
