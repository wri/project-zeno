"""Notification email subscriptions for a user's own dashboards."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth.dependencies import require_auth
from src.api.repositories import dashboard_writer
from src.api.repositories.subscription_repository import (
    PostgresSubscriptionRepository,
)
from src.api.routers.dashboards import _expanded_response, _refetch_dashboard
from src.api.schemas import (
    BulkSubscriptionsRequest,
    BulkSubscriptionsResponse,
    DashboardResponse,
    DashboardSubscriptionsRequest,
    UserModel,
)
from src.api.services.subscription import (
    NotEligibleForSubscriptionError,
    SubscriptionChannel,
    SubscriptionService,
    SubscriptionTarget,
)
from src.shared.database import get_session_from_pool_dependency

router = APIRouter()


def get_subscription_service() -> SubscriptionService:
    return SubscriptionService(PostgresSubscriptionRepository())


@router.put(
    "/api/dashboards/{dashboard_id}/subscriptions",
    response_model=DashboardResponse,
)
async def set_dashboard_subscriptions(
    dashboard_id: UUID,
    body: DashboardSubscriptionsRequest,
    user: UserModel = Depends(require_auth),
    service: SubscriptionService = Depends(get_subscription_service),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """Sets which channels the dashboard is subscribed to for the listed
    datasets. Only the dashboard owner can change them.

    The body lists the channels to subscribe to, so an empty list
    unsubscribes from them all. Email needs a dashboard that is eligible for
    subscription, or 409.
    """
    dashboard = await dashboard_writer.get_dashboard(dashboard_id)
    if dashboard is None or dashboard.user_id != user.id:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    aoi = min(dashboard.aois, key=lambda a: a.position, default=None)
    if aoi is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Subscriptions need a dashboard with an area",
        )

    target = SubscriptionTarget(
        dashboard_id=dashboard.id,
        aoi_id=aoi.id,
        user_id=dashboard.user_id,
        eligible_for_subscription=dashboard.eligible_for_subscription,
    )
    try:
        await service.update(target, set(body.datasets), set(body.channels))
    except NotEligibleForSubscriptionError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        )
    return await _expanded_response(
        await _refetch_dashboard(dashboard_id), user, session
    )


@router.delete("/api/subscriptions", response_model=BulkSubscriptionsResponse)
async def turn_off_all_subscriptions(
    channel: SubscriptionChannel,
    user: UserModel = Depends(require_auth),
    service: SubscriptionService = Depends(get_subscription_service),
):
    """Turns the channel off for every dashboard the user subscribed, in one
    transaction, and lists the dashboards that changed."""
    changed = await service.remove_for_user(user.id, channel)
    return BulkSubscriptionsResponse(dashboard_ids=changed)


@router.put("/api/subscriptions", response_model=BulkSubscriptionsResponse)
async def turn_on_subscriptions(
    body: BulkSubscriptionsRequest,
    user: UserModel = Depends(require_auth),
    service: SubscriptionService = Depends(get_subscription_service),
):
    """Turns the channel on for the user's own dashboards in the list, for
    example to undo turning them all off. Dashboards that are not eligible, or
    not the user's, are skipped and listed."""
    result = await service.add_for_user(
        user.id, body.channel, body.dashboard_ids
    )
    return BulkSubscriptionsResponse(
        dashboard_ids=result.subscribed, skipped=result.skipped
    )
