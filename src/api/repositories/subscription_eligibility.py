"""Keeps each dashboard's eligibility for email alerts up to date.

A dashboard is eligible while it has an integrated alerts widget: an insight
with an integrated alerts chart, or a map or alerts widget showing that
dataset. When a dashboard stops being eligible, its email alerts go off, and
the owner has to turn them on again once the widget is back.
"""

from uuid import UUID

from sqlalchemy import exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.datasets.handlers.analytics_handler import INTEGRATED_ALERTS_ID
from src.api.data_models import (
    DashboardOrm,
    DashboardWidgetOrm,
    InsightChartOrm,
)
from src.api.repositories.subscription_repository import (
    remove_email_subscriptions,
)


async def refresh_subscription_eligibility(
    session: AsyncSession, dashboard_id: UUID
) -> None:
    """Recomputes the dashboard's eligibility inside the caller's
    transaction, after its widgets changed."""
    await session.flush()
    widget = DashboardWidgetOrm
    alerts_insights = select(InsightChartOrm.insight_id).where(
        InsightChartOrm.dataset_id == INTEGRATED_ALERTS_ID
    )
    eligible = await session.scalar(
        select(
            exists().where(
                widget.dashboard_id == dashboard_id,
                or_(
                    widget.insight_id.in_(alerts_insights),
                    widget.config["dataset"]["dataset_id"].astext
                    == str(INTEGRATED_ALERTS_ID),
                ),
            )
        )
    )
    # Setting updated_at to itself keeps the dashboard's "last updated"
    # time, which only the owner's own edits should move.
    await session.execute(
        update(DashboardOrm)
        .where(DashboardOrm.id == dashboard_id)
        .values(
            eligible_for_subscription=eligible,
            updated_at=DashboardOrm.updated_at,
        )
    )
    if not eligible:
        await remove_email_subscriptions(session, dashboard_id)
