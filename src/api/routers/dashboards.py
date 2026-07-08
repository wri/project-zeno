"""Dashboard management endpoints.

A dashboard is a persistent, curated collection of insights, layers and AOIs.
Widgets reference insights (payloads are expanded on the single-dashboard
endpoint so the frontend renders them like insights); AOIs are stored as
canonical (source, src_id, subtype) references plus a display name, never
geometry. Same access rules as insights (own + public read, owner-only edit,
admin/superuser override, 404 for not-found *and* not-owned), with one twist:
publishing a dashboard cascades ``is_public=True`` to its referenced insights,
otherwise a public dashboard renders empty for viewers.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.api.auth.dependencies import optional_auth, require_auth
from src.api.data_models import DashboardOrm, InsightOrm, UserType
from src.api.repositories import dashboard_writer
from src.api.repositories.insight_access import (
    is_visible_to_user as insight_is_visible_to_user,
)
from src.api.routers.insights import (
    _row_to_response as _insight_row_to_response,
)
from src.api.schemas import (
    DashboardAoiResponse,
    DashboardCreateRequest,
    DashboardPublicToggleRequest,
    DashboardPublicToggleResponse,
    DashboardResponse,
    DashboardUpdateRequest,
    DashboardWidgetCreateRequest,
    DashboardWidgetResponse,
    DashboardWidgetUpdateRequest,
    UserModel,
)
from src.shared.database import get_session_from_pool_dependency
from src.shared.logging_config import get_logger
from src.shared.tile_urls import absolutize_widget_config

logger = get_logger(__name__)

router = APIRouter()


def _is_privileged(user: Optional[UserModel]) -> bool:
    return user is not None and user.user_type in (
        UserType.ADMIN,
        UserType.SUPERUSER,
    )


def _row_to_response(
    row: DashboardOrm,
    insights_by_id: Optional[dict] = None,
) -> DashboardResponse:
    """Map a dashboard row (with aois + widgets loaded) to the response.

    ``insights_by_id`` carries the pre-loaded insight rows the viewer may see;
    widgets referencing anything else keep ``insight=None``.
    """
    insights_by_id = insights_by_id or {}
    return DashboardResponse(
        id=row.id,
        user_id=row.user_id,
        name=row.name,
        description=row.description,
        is_public=row.is_public,
        created_at=row.created_at,
        updated_at=row.updated_at,
        aois=[
            DashboardAoiResponse.model_validate(aoi) for aoi in row.aois or []
        ],
        widgets=[
            DashboardWidgetResponse(
                id=widget.id,
                position=widget.position,
                widget_type=widget.widget_type,
                insight_id=widget.insight_id,
                config=absolutize_widget_config(widget.config) or {},
                created_at=widget.created_at,
                insight=(
                    _insight_row_to_response(insights_by_id[widget.insight_id])
                    if widget.insight_id in insights_by_id
                    else None
                ),
            )
            for widget in row.widgets or []
        ],
    )


async def _get_owned_dashboard(
    dashboard_id: UUID, user: UserModel
) -> DashboardOrm:
    """Load a dashboard the user may edit, or raise 404 (not-found and
    not-owned are indistinguishable, like insights)."""
    row = await dashboard_writer.get_dashboard(dashboard_id)
    if row is None or (row.user_id != user.id and not _is_privileged(user)):
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return row


async def _refetch_dashboard(dashboard_id) -> DashboardOrm:
    """Re-load a dashboard just written to; 404 only on a concurrent delete."""
    row = await dashboard_writer.get_dashboard(dashboard_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return row


@router.post(
    "/api/dashboards",
    response_model=DashboardResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_dashboard(
    body: DashboardCreateRequest,
    user: UserModel = Depends(require_auth),
):
    """Create a dashboard for one area (MVP: exactly one AOI)."""
    dashboard_id = await dashboard_writer.create_dashboard(
        user_id=user.id,
        name=body.name or body.aois[0].name,
        description=body.description,
        aois=[aoi.model_dump() for aoi in body.aois],
    )
    return _row_to_response(await _refetch_dashboard(dashboard_id))


@router.get("/api/dashboards", response_model=list[DashboardResponse])
async def list_dashboards(
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """List the authenticated user's dashboards, newest first."""
    result = await session.execute(
        select(DashboardOrm)
        .options(
            selectinload(DashboardOrm.aois),
            selectinload(DashboardOrm.widgets),
        )
        .where(DashboardOrm.user_id == user.id)
        .order_by(DashboardOrm.created_at.desc())
    )
    return [_row_to_response(row) for row in result.scalars().all()]


@router.get("/api/dashboards/{dashboard_id}", response_model=DashboardResponse)
async def get_dashboard(
    dashboard_id: UUID,
    user: Optional[UserModel] = Depends(optional_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """
    Get a single dashboard with widget insight payloads expanded.

    Public dashboards can be accessed by anyone; private ones require
    authentication and ownership. Same read rule as
    `src.api.repositories.dashboard_access` (used by the agent tools), plus
    the admin/superuser override and HTTP error semantics.
    """
    row = await dashboard_writer.get_dashboard(dashboard_id)
    if not row:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    if not row.is_public:
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        if row.user_id != user.id and not _is_privileged(user):
            raise HTTPException(status_code=404, detail="Dashboard not found")

    # Expand widget insights the viewer may see (own + public; read-through
    # access for private insights on public dashboards is deliberately not
    # granted). Privileged users see everything.
    insight_ids = [w.insight_id for w in row.widgets if w.insight_id]
    insights_by_id = {}
    if insight_ids:
        result = await session.execute(
            select(InsightOrm)
            .options(selectinload(InsightOrm.charts))
            .where(InsightOrm.id.in_(insight_ids))
        )
        user_id = user.id if user else None
        insights_by_id = {
            insight.id: insight
            for insight in result.scalars().all()
            if insight_is_visible_to_user(insight, user_id)
            or _is_privileged(user)
        }
    return _row_to_response(row, insights_by_id)


@router.patch(
    "/api/dashboards/{dashboard_id}", response_model=DashboardResponse
)
async def update_dashboard(
    dashboard_id: UUID,
    body: DashboardUpdateRequest,
    user: UserModel = Depends(require_auth),
):
    """Rename a dashboard or update its description (owner only)."""
    await _get_owned_dashboard(dashboard_id, user)
    await dashboard_writer.update_dashboard(
        dashboard_id, name=body.name, description=body.description
    )
    return _row_to_response(await _refetch_dashboard(dashboard_id))


@router.patch(
    "/api/dashboards/{dashboard_id}/public",
    response_model=DashboardPublicToggleResponse,
)
async def toggle_dashboard_public(
    dashboard_id: UUID,
    body: DashboardPublicToggleRequest,
    user: UserModel = Depends(require_auth),
):
    """Set or unset is_public on a dashboard owned by the authenticated user.

    Publishing cascades ``is_public=True`` to all insights referenced by the
    dashboard's widgets; the response lists the insight ids it publicized.
    Unpublishing does not cascade.
    """
    await _get_owned_dashboard(dashboard_id, user)
    publicized = await dashboard_writer.set_dashboard_public(
        dashboard_id, body.is_public
    )
    base = _row_to_response(await _refetch_dashboard(dashboard_id))
    return DashboardPublicToggleResponse(
        **base.model_dump(),
        publicized_insight_ids=[UUID(i) for i in publicized or []],
    )


@router.post(
    "/api/dashboards/{dashboard_id}/widgets",
    response_model=DashboardResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_widget(
    dashboard_id: UUID,
    body: DashboardWidgetCreateRequest,
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """Add a widget to a dashboard (owner only).

    Insight widgets must reference an insight the user can see (own or
    public) — the same rule the agent tools apply.
    """
    await _get_owned_dashboard(dashboard_id, user)

    if body.widget_type == "insight":
        if body.insight_id is None:
            raise HTTPException(
                status_code=422,
                detail="insight widgets require an insight_id",
            )
        insight = await session.get(InsightOrm, body.insight_id)
        if insight is None or not (
            insight_is_visible_to_user(insight, user.id)
            or _is_privileged(user)
        ):
            raise HTTPException(status_code=404, detail="Insight not found")

    try:
        await dashboard_writer.add_widget(
            dashboard_id,
            widget_type=body.widget_type,
            insight_id=str(body.insight_id) if body.insight_id else None,
            config=body.config,
            position=body.position,
        )
    except dashboard_writer.DuplicateInsightWidgetError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="insight is already on this dashboard",
        )
    return _row_to_response(await _refetch_dashboard(dashboard_id))


@router.patch(
    "/api/dashboards/{dashboard_id}/widgets/{widget_id}",
    response_model=DashboardResponse,
)
async def update_widget(
    dashboard_id: UUID,
    widget_id: UUID,
    body: DashboardWidgetUpdateRequest,
    user: UserModel = Depends(require_auth),
):
    """Reorder a widget or update its presentation config (owner only)."""
    row = await _get_owned_dashboard(dashboard_id, user)
    if widget_id not in {w.id for w in row.widgets}:
        raise HTTPException(status_code=404, detail="Widget not found")
    await dashboard_writer.update_widget(
        widget_id, position=body.position, config=body.config
    )
    return _row_to_response(await _refetch_dashboard(dashboard_id))


@router.delete(
    "/api/dashboards/{dashboard_id}/widgets/{widget_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_widget(
    dashboard_id: UUID,
    widget_id: UUID,
    user: UserModel = Depends(require_auth),
):
    """Remove a widget from a dashboard (owner only); the insight it
    references is left intact."""
    row = await _get_owned_dashboard(dashboard_id, user)
    if widget_id not in {w.id for w in row.widgets}:
        raise HTTPException(status_code=404, detail="Widget not found")
    await dashboard_writer.remove_widget(widget_id)


@router.delete(
    "/api/dashboards/{dashboard_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_dashboard(
    dashboard_id: UUID,
    user: UserModel = Depends(require_auth),
):
    """Delete a dashboard with its widgets (owner only); referenced insights
    are left intact."""
    await _get_owned_dashboard(dashboard_id, user)
    await dashboard_writer.delete_dashboard(dashboard_id)
