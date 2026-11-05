"""Alert subscriptions for a user's own dashboards."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth.dependencies import require_auth
from src.api.repositories import dashboard_writer
from src.api.repositories.email_eligibility import DashboardEmailEligibility
from src.api.repositories.subscription_repository import (
    PostgresSubscriptionRepository,
)
from src.api.routers.dashboards import _expanded_response, _refetch_dashboard
from src.api.schemas import (
    DashboardResponse,
    DashboardSubscriptionsRequest,
    UserModel,
)
from src.api.services.subscription import (
    EmailAlertsUnavailableError,
    SubscriptionService,
    SubscriptionTarget,
)
from src.shared.database import get_session_from_pool_dependency

router = APIRouter()


def get_subscription_service() -> SubscriptionService:
    return SubscriptionService(
        PostgresSubscriptionRepository(), DashboardEmailEligibility()
    )


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
    """Sets which alert modes are on for the listed datasets. Only the
    dashboard owner can change them.

    The body lists the modes that should be on, so an empty list turns
    everything off. Email can't be on without in-app, and needs an
    integrated alerts chart and a GADM admin area on the dashboard, or 409.
    """
    dashboard = await dashboard_writer.get_dashboard(dashboard_id)
    if dashboard is None or dashboard.user_id != user.id:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    aoi = min(dashboard.aois, key=lambda a: a.position, default=None)
    if aoi is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Alerts need a dashboard with an area",
        )

    target = SubscriptionTarget(
        dashboard_id=dashboard.id, aoi_id=aoi.id, user_id=dashboard.user_id
    )
    try:
        await service.update(target, set(body.datasets), set(body.modes))
    except EmailAlertsUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        )
    return await _expanded_response(
        await _refetch_dashboard(dashboard_id), user, session
    )
