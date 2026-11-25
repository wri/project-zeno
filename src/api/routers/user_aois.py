"""The user's areas ("My areas"): custom areas they own and reference areas
they saved, as ``user_aois`` rows.

A saved area is a link to the shared ``aois`` row and never a copy of its
geometry, so renaming or removing it changes only the user's areas.
"""

from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Response,
)
from sqlalchemy import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth.dependencies import require_auth
from src.api.data_models import AoiRelationship, CustomAreaOrm
from src.api.repositories import custom_area_writer, user_aoi_repository
from src.api.routers.custom_areas import get_custom_aoi_analytics_service
from src.api.schemas import (
    UserAoiCreate,
    UserAoiModel,
    UserAoiRename,
    UserModel,
)
from src.api.services.custom_aoi_analytics import (
    CustomAoiAnalyticsService,
    custom_aoi_payload,
)
from src.shared.database import get_session_from_pool_dependency
from src.shared.geocoding_helpers import _response_src_id, normalize_aoi_source

router = APIRouter()


def _row_to_response(row: RowMapping) -> UserAoiModel:
    return UserAoiModel(
        **{**row, "src_id": _response_src_id(row["source"], row["src_id"])}
    )


async def _get_user_aoi(
    session: AsyncSession, user_id: str, user_aoi_id: UUID
) -> RowMapping:
    """Get one of the user's areas, or raise 404 (not-found and not-owned
    are indistinguishable)."""
    user_aoi = await user_aoi_repository.get_user_aoi(
        session, user_id, user_aoi_id
    )
    if user_aoi is None:
        raise HTTPException(status_code=404, detail="Area not found")
    return user_aoi


async def _get_owned_custom_area(
    session: AsyncSession, user_id: str, area_id: UUID
) -> CustomAreaOrm:
    """Get a custom area the user owns, or raise 404."""
    area = await custom_area_writer.get_owned_custom_area(
        session, user_id, area_id
    )
    if area is None:
        raise HTTPException(status_code=404, detail="Area not found")
    return area


@router.get("/api/user_aois", response_model=list[UserAoiModel])
async def list_user_aois(
    response: Response,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """List the caller's areas, newest first, without geometry.

    When more results are available, the next page offset is returned in the
    ``X-Next-Offset`` response header.
    """
    # One extra row shows whether another page exists.
    rows = await user_aoi_repository.list_user_aois(
        session, user.id, limit + 1, offset
    )
    if len(rows) > limit:
        rows = rows[:limit]
        response.headers["X-Next-Offset"] = str(offset + limit)
    return [_row_to_response(row) for row in rows]


@router.post("/api/user_aois", response_model=UserAoiModel, status_code=201)
async def save_user_aoi(
    area: UserAoiCreate,
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """Save a source area, such as a GADM country, to the caller's areas.

    Returns 404 for an unknown area and 409 if it is already saved. Custom
    areas are in their owner's areas from the moment they are drawn.
    """
    try:
        source = normalize_aoi_source(area.source)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    if source == "custom":
        raise HTTPException(
            status_code=422, detail="Custom areas are already in your areas"
        )
    aoi_id = await user_aoi_repository.get_reference_aoi_id(
        session, source, str(area.src_id)
    )
    if aoi_id is None:
        raise HTTPException(status_code=404, detail="Area not found")
    user_aoi_id = await user_aoi_repository.create_saved_aoi(
        session, user.id, aoi_id, area.name
    )
    if user_aoi_id is None:
        raise HTTPException(
            status_code=409, detail="Area is already in your areas"
        )
    await session.commit()
    return _row_to_response(await _get_user_aoi(session, user.id, user_aoi_id))


@router.patch("/api/user_aois/{user_aoi_id}", response_model=UserAoiModel)
async def rename_user_aoi(
    user_aoi_id: UUID,
    rename: UserAoiRename,
    background_tasks: BackgroundTasks,
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
    analytics_service: CustomAoiAnalyticsService = Depends(
        get_custom_aoi_analytics_service
    ),
):
    """Rename one of the caller's areas.

    A saved area gets the caller's own label; the shared area keeps its name.
    An owned custom area is renamed itself.
    """
    user_aoi = await _get_user_aoi(session, user.id, user_aoi_id)
    if user_aoi["relationship"] == AoiRelationship.OWNER:
        area = await _get_owned_custom_area(
            session, user.id, UUID(user_aoi["src_id"])
        )
        await custom_area_writer.update_custom_area_name(
            session, area, rename.name
        )
        await session.commit()
        background_tasks.add_task(
            analytics_service.save, [custom_aoi_payload(area)]
        )
    else:
        await user_aoi_repository.update_saved_aoi_name(
            session, user_aoi_id, rename.name
        )
        await session.commit()
    return _row_to_response(await _get_user_aoi(session, user.id, user_aoi_id))


@router.delete("/api/user_aois/{user_aoi_id}", status_code=204)
async def delete_user_aoi(
    user_aoi_id: UUID,
    background_tasks: BackgroundTasks,
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
    analytics_service: CustomAoiAnalyticsService = Depends(
        get_custom_aoi_analytics_service
    ),
):
    """Remove an area from the caller's areas.

    A saved area loses only its link. An owned custom area is deleted.
    Dashboards on the area are not touched.
    """
    user_aoi = await _get_user_aoi(session, user.id, user_aoi_id)
    if user_aoi["relationship"] == AoiRelationship.OWNER:
        area_id = UUID(user_aoi["src_id"])
        area = await _get_owned_custom_area(session, user.id, area_id)
        await custom_area_writer.delete_custom_area(session, area)
        await session.commit()
        background_tasks.add_task(analytics_service.delete, area_id)
    else:
        await user_aoi_repository.delete_saved_aoi(session, user_aoi_id)
        await session.commit()
