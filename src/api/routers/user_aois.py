"""The user's area library: custom areas they own and reference areas they
saved, as ``user_aois`` rows."""

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth.dependencies import require_auth
from src.api.repositories.user_aoi_repository import list_user_aois
from src.api.schemas import UserAoiModel, UserModel
from src.shared.database import get_session_from_pool_dependency
from src.shared.geocoding_helpers import _response_src_id

router = APIRouter()


@router.get("/api/user_aois", response_model=list[UserAoiModel])
async def list_user_aois_endpoint(
    response: Response,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """List the caller's library, newest first, without geometry.

    When more results are available, the next page offset is returned in the
    ``X-Next-Offset`` response header.
    """
    # One extra row shows whether another page exists.
    rows = await list_user_aois(session, user.id, limit + 1, offset)
    if len(rows) > limit:
        rows = rows[:limit]
        response.headers["X-Next-Offset"] = str(offset + limit)
    return [
        UserAoiModel(
            **{**row, "src_id": _response_src_id(row["source"], row["src_id"])}
        )
        for row in rows
    ]
