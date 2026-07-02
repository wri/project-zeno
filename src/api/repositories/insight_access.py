"""Who may see or edit an insight — the single place that rule lives.

Read rule: a user sees their own insights plus public ones.
Edit rule: only the owner may edit. Owner-less rows (user_id NULL, e.g. old
CLI runs) are neither visible nor editable through the agent tools.

Both rules take the user id from the caller (the agent tools read it from the
request-scoped structlog context bound by the auth dependency) and treat a
missing user id as "not authenticated": nothing private is visible, nothing is
editable.

The API router (``src/api/routers/insights.py``) implements the same read rule
with two extras that don't apply to agent tools — admin/superuser override and
HTTP error semantics — so it stays separate.
"""

from typing import Optional

from sqlalchemy import or_
from sqlalchemy.sql.elements import ColumnElement

from src.api.data_models import InsightOrm


def visible_insights_clause(user_id: Optional[str]) -> ColumnElement:
    """SQL WHERE clause selecting the insights `user_id` may see."""
    if user_id:
        return or_(
            InsightOrm.is_public.is_(True),
            InsightOrm.user_id == user_id,
        )
    return InsightOrm.is_public.is_(True)


def is_visible_to_user(row: InsightOrm, user_id: Optional[str]) -> bool:
    """Python twin of `visible_insights_clause` for already-loaded rows."""
    return bool(row.is_public or (user_id and row.user_id == user_id))


def is_editable_by_user(row: InsightOrm, user_id: Optional[str]) -> bool:
    """Only the owner may edit; unauthenticated callers edit nothing."""
    return bool(user_id and row.user_id == user_id)
