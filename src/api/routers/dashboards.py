"""Dashboard management endpoints.

A dashboard is a persistent, curated collection of insights, layers and AOIs.
Widgets reference insights (payloads are expanded on the single-dashboard
endpoint so the frontend renders them like insights); AOIs are stored as
canonical (source, src_id, subtype) references plus a display name, never
geometry. Widgets optionally belong to a section — one level of grouping,
with the ungrouped widgets rendering above the first section.
Same access rules as insights (own + public read, owner-only edit,
admin/superuser override, 404 for not-found *and* not-owned), with one twist:
publishing a dashboard cascades ``is_public=True`` to its referenced insights,
otherwise a public dashboard renders empty for viewers.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
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
    DashboardSectionCreateRequest,
    DashboardSectionResponse,
    DashboardSectionUpdateRequest,
    DashboardUpdateRequest,
    DashboardWidgetCreateRequest,
    DashboardWidgetResponse,
    DashboardWidgetUpdateRequest,
    NrtSectionCreateRequest,
    NrtSectionRefreshRequest,
    NrtSectionResponse,
    UserModel,
)
from src.api.services.nrt_monitoring import (
    SECTION_TYPE as NRT_SECTION_TYPE,
)
from src.api.services.nrt_monitoring import (
    AnalyticsFailedError,
    build_nrt_section,
    find_existing_section,
    refresh_nrt_section,
    resolve_period,
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
    """Map a dashboard row (aois + sections + widgets loaded) to the response.

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
        sections=[
            DashboardSectionResponse.model_validate(section)
            for section in row.sections or []
        ],
        widgets=[
            DashboardWidgetResponse(
                id=widget.id,
                position=widget.position,
                section_id=widget.section_id,
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


def _sealed_conflict(error: dashboard_writer.SealedSectionError):
    """409 for a write to a section a recipe sealed.

    A conflict, not a permission error: the owner is refused because of what
    the section *is*, and the same call against any other section succeeds.
    """
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"Section is read-only (type: {error.section_type})",
    )


async def _visible_insights(
    session: AsyncSession, row: DashboardOrm, user: Optional[UserModel]
) -> dict:
    """The insight rows behind this dashboard's widgets that the viewer may
    see (own + public; read-through access for private insights on public
    dashboards is deliberately not granted). Privileged users see
    everything.

    Shared by every endpoint that returns a dashboard the caller is about to
    render, so a widget's payload does not depend on which call produced it.
    """
    insight_ids = [w.insight_id for w in row.widgets if w.insight_id]
    if not insight_ids:
        return {}
    result = await session.execute(
        select(InsightOrm)
        .options(selectinload(InsightOrm.charts))
        .where(InsightOrm.id.in_(insight_ids))
    )
    user_id = user.id if user else None
    return {
        insight.id: insight
        for insight in result.scalars().all()
        if insight_is_visible_to_user(insight, user_id) or _is_privileged(user)
    }


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
            selectinload(DashboardOrm.sections),
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

    return _row_to_response(row, await _visible_insights(session, row, user))


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
    "/api/dashboards/{dashboard_id}/sections",
    response_model=DashboardResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_section(
    dashboard_id: UUID,
    body: DashboardSectionCreateRequest,
    user: UserModel = Depends(require_auth),
):
    """Add a section to a dashboard (owner only).

    Sections group widgets under a heading; a widget joins one by carrying
    its ``section_id``. The section starts empty.
    """
    await _get_owned_dashboard(dashboard_id, user)
    await dashboard_writer.add_section(
        dashboard_id,
        title=body.title,
        description=body.description,
        position=body.position,
        type=body.type,
    )
    return _row_to_response(await _refetch_dashboard(dashboard_id))


@router.post(
    "/api/dashboards/{dashboard_id}/sections/nrt-monitoring",
    response_model=NrtSectionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_nrt_monitoring_section(
    dashboard_id: UUID,
    # default_factory, not a shared instance: one request must not be able
    # to see another's body object.
    body: NrtSectionCreateRequest = Body(
        default_factory=NrtSectionCreateRequest
    ),
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """Build a near-real-time monitoring section for the dashboard's area
    (owner only).

    One call creates a whole section: a chart of disturbance alerts over the
    period, a map of those alerts, and satellite imagery of the same area and
    period. Everything runs before the response, so the section is complete
    when this returns — expect it to take tens of seconds.

    The section is **read-only** afterwards (``type: "nrt-monitoring"``):
    writes to it or its widgets return 409. To change one, delete it and
    build another.

    Satellite imagery is best-effort: areas above the mosaic size limit, or
    periods with no cloud-free scenes, yield a two-widget section and a line
    in ``warnings``. A failure to pull the alert data returns 502 — a section
    without its data would say nothing.

    Called twice for the same period, the second call returns the existing
    section with ``created: false``; pass ``force: true`` to build anyway.
    """
    dashboard = await _get_owned_dashboard(dashboard_id, user)
    if not dashboard.aois:
        raise HTTPException(
            status_code=422,
            detail="Dashboard has no area to monitor",
        )

    aoi = dashboard.aois[0]
    start_date, end_date = await resolve_period(body.days)

    if not body.force:
        existing = find_existing_section(dashboard, start_date, end_date)
        if existing is not None:
            base = _row_to_response(
                dashboard, await _visible_insights(session, dashboard, user)
            )
            window = existing.config or {}
            return NrtSectionResponse(
                **base.model_dump(),
                section_id=existing.id,
                created=False,
                days=window.get("days", body.days),
                start_date=window.get("start_date", start_date),
                end_date=window.get("end_date", end_date),
            )

    try:
        result = await build_nrt_section(
            str(dashboard_id),
            {
                "source": aoi.source,
                "src_id": aoi.src_id,
                "subtype": aoi.subtype,
                "name": aoi.name,
            },
            user_id=user.id,
            days=body.days,
            window_days=body.window_days,
            max_cloud_cover=body.max_cloud_cover,
            title=body.title,
            description=body.description,
            language=user.preferred_language_code,
        )
    except AnalyticsFailedError as error:
        logger.error(
            "nrt_section_analytics_failed",
            severity="high",
            dashboard_id=str(dashboard_id),
            error_details=str(error),
        )
        raise HTTPException(
            status_code=502,
            detail=f"Could not retrieve alert data: {error}",
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    row = await _refetch_dashboard(dashboard_id)
    base = _row_to_response(row, await _visible_insights(session, row, user))
    return NrtSectionResponse(
        **base.model_dump(),
        section_id=UUID(result.section_id),
        created=True,
        days=result.days,
        start_date=result.start_date,
        end_date=result.end_date,
        warnings=result.warnings,
    )


@router.post(
    "/api/dashboards/{dashboard_id}/sections/{section_id}/refresh",
    response_model=NrtSectionResponse,
)
async def refresh_monitoring_section(
    dashboard_id: UUID,
    section_id: UUID,
    body: NrtSectionRefreshRequest = Body(
        default_factory=NrtSectionRefreshRequest
    ),
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """Move a monitoring section to a new time window (owner only).

    The one-click way to change the period on screen. Everything the section
    shows moves together: the alerts chart is recomputed, the alerts layer
    re-cut to the new dates, the satellite imagery rebuilt for the new period
    end, and the title and description rewritten — they state the period, so
    keeping the old ones would make the section lie.

    The section keeps its id and its place on the dashboard, so a link to it
    still works. Its previous chart is deleted once nothing points at it.
    Like the build, this runs before the response: expect tens of seconds.

    Only `nrt-monitoring` sections can be refreshed — a hand-composed
    section has no recipe to re-run, and returns 422. The read-only rule is
    not being bent here: a refresh replaces the section's content wholesale
    on the recipe's own terms, which is exactly what a client cannot do
    widget by widget.
    """
    dashboard = await _get_owned_dashboard(dashboard_id, user)
    section = next((s for s in dashboard.sections if s.id == section_id), None)
    if section is None:
        raise HTTPException(status_code=404, detail="Section not found")
    if section.type != NRT_SECTION_TYPE:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Section type '{section.type}' has no recipe to refresh; "
                f"only '{NRT_SECTION_TYPE}' sections can be."
            ),
        )
    if not dashboard.aois:
        raise HTTPException(
            status_code=422, detail="Dashboard has no area to monitor"
        )

    aoi = dashboard.aois[0]
    try:
        result = await refresh_nrt_section(
            str(section_id),
            {
                "source": aoi.source,
                "src_id": aoi.src_id,
                "subtype": aoi.subtype,
                "name": aoi.name,
            },
            user_id=user.id,
            days=body.days,
            window_days=body.window_days,
            max_cloud_cover=body.max_cloud_cover,
            language=user.preferred_language_code,
        )
    except AnalyticsFailedError as error:
        logger.error(
            "nrt_section_refresh_analytics_failed",
            severity="high",
            section_id=str(section_id),
            error_details=str(error),
        )
        raise HTTPException(
            status_code=502,
            detail=f"Could not retrieve alert data: {error}",
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Section not found")

    row = await _refetch_dashboard(dashboard_id)
    base = _row_to_response(row, await _visible_insights(session, row, user))
    return NrtSectionResponse(
        **base.model_dump(),
        section_id=section_id,
        created=False,
        days=result.days,
        start_date=result.start_date,
        end_date=result.end_date,
        warnings=result.warnings,
    )


@router.patch(
    "/api/dashboards/{dashboard_id}/sections/{section_id}",
    response_model=DashboardResponse,
)
async def update_section(
    dashboard_id: UUID,
    section_id: UUID,
    body: DashboardSectionUpdateRequest,
    user: UserModel = Depends(require_auth),
):
    """Retitle, restate or reorder a section (owner only).

    An explicit null ``description`` clears it; omitting the field leaves
    the existing text alone.
    """
    row = await _get_owned_dashboard(dashboard_id, user)
    if section_id not in {s.id for s in row.sections}:
        raise HTTPException(status_code=404, detail="Section not found")
    description: object = dashboard_writer.UNSET
    if "description" in body.model_fields_set:
        description = body.description
    try:
        await dashboard_writer.update_section(
            section_id,
            title=body.title,
            description=description,
            position=body.position,
        )
    except dashboard_writer.SealedSectionError as error:
        raise _sealed_conflict(error)
    return _row_to_response(await _refetch_dashboard(dashboard_id))


@router.delete(
    "/api/dashboards/{dashboard_id}/sections/{section_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_section(
    dashboard_id: UUID,
    section_id: UUID,
    delete_widgets: bool = Query(
        False,
        description=(
            "Also delete the widgets in the section. Off by default: the "
            "widgets survive and fall back to the ungrouped top level. "
            "Insights the deleted widgets referenced are left intact."
        ),
    ),
    user: UserModel = Depends(require_auth),
):
    """Delete a section (owner only).

    By default this is a grouping change, not a content deletion: the
    section's widgets stay on the dashboard and fall back to the ungrouped
    top level, renumbered after the widgets already there. Pass
    ``delete_widgets=true`` to remove them with the section.

    A read-only section built by a recipe (``type`` other than ``default``)
    is the exception: deleting it always removes its widgets, whatever
    ``delete_widgets`` says, because those widgets are only editable — and
    only meaningful — inside their own section.
    """
    row = await _get_owned_dashboard(dashboard_id, user)
    if section_id not in {s.id for s in row.sections}:
        raise HTTPException(status_code=404, detail="Section not found")
    await dashboard_writer.remove_section(
        section_id, delete_widgets=delete_widgets
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
            section_id=str(body.section_id) if body.section_id else None,
        )
    except dashboard_writer.DuplicateInsightWidgetError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="insight is already on this dashboard",
        )
    except dashboard_writer.UnknownSectionError:
        raise HTTPException(status_code=404, detail="Section not found")
    except dashboard_writer.SealedSectionError as error:
        raise _sealed_conflict(error)
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
    """Reorder a widget, move it between sections, or update its
    presentation config (owner only).

    ``section_id`` is three-valued: omitted leaves the grouping alone, a
    section id moves the widget into that section, an explicit null moves it
    back to the ungrouped top level.
    """
    row = await _get_owned_dashboard(dashboard_id, user)
    if widget_id not in {w.id for w in row.widgets}:
        raise HTTPException(status_code=404, detail="Widget not found")
    section_id: object = dashboard_writer.UNSET
    if "section_id" in body.model_fields_set:
        section_id = str(body.section_id) if body.section_id else None
    try:
        await dashboard_writer.update_widget(
            widget_id,
            position=body.position,
            config=body.config,
            section_id=section_id,
        )
    except dashboard_writer.UnknownSectionError:
        raise HTTPException(status_code=404, detail="Section not found")
    except dashboard_writer.SealedSectionError as error:
        raise _sealed_conflict(error)
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
    try:
        await dashboard_writer.remove_widget(widget_id)
    except dashboard_writer.SealedSectionError as error:
        raise _sealed_conflict(error)


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
