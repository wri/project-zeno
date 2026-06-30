"""Unified AOI search endpoint.

Searches Areas of Interest across all sources (gadm / kba / wdpa / landmark /
custom) by name and/or source type, reusing the same pg_trgm search core as the
agent's ``pick_aoi`` geocoder.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from src.api.auth.dependencies import require_auth
from src.api.schemas import AOISearchResult, UserModel
from src.shared.geocoding_helpers import normalize_aoi_source, search_aois
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("/api/aois", response_model=list[AOISearchResult])
async def search_aois_endpoint(
    response: Response,
    name: Optional[str] = Query(
        default=None, description="Fuzzy name to search for. Omit to browse."
    ),
    source: List[str] = Query(
        default=[],
        description=(
            "Source(s) to filter by: gadm, kba, wdpa (protectedareas), "
            "landmark, custom. Repeatable; omit to search all sources."
        ),
    ),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: UserModel = Depends(require_auth),
):
    """Search/browse AOIs by name and source type.

    - Provide ``name`` for fuzzy, similarity-ranked search.
    - Omit ``name`` to browse AOIs alphabetically within the selected source(s).
    - ``source`` may be repeated to search several sources at once; omitting it
      searches all available sources. Custom areas are scoped to the caller.

    When more results are available, the next page offset is returned in the
    ``X-Next-Offset`` response header.
    """
    try:
        sources = [normalize_aoi_source(s) for s in source] if source else None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        # Fetch one extra row to determine whether more pages exist.
        df = await search_aois(
            name=name,
            sources=sources,
            user_id=user.id,
            limit=limit + 1,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    rows = df.to_dict(orient="records")
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]
        response.headers["X-Next-Offset"] = str(offset + limit)

    return [AOISearchResult(**row) for row in rows]
