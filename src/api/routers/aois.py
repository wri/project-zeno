"""Unified AOI search endpoint.

Searches Areas of Interest across all sources (gadm / kba / wdpa / landmark /
custom) by name and/or source type, reusing the same search core as the
agent's ``pick_aoi`` geocoder (see docs/aoi-full-text-search.md).
"""

from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from src.api.auth.dependencies import require_auth
from src.api.schemas import AOISearchResult, UserModel
from src.shared.aoi_search import (
    MAX_SEARCH_NAME_CHARS,
    MAX_SEARCH_OFFSET,
    SearchRequestError,
    search_aois,
)
from src.shared.geocoding_helpers import normalize_aoi_source
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("/api/aois", response_model=list[AOISearchResult])
async def search_aois_endpoint(
    response: Response,
    name: Optional[str] = Query(
        default=None,
        max_length=MAX_SEARCH_NAME_CHARS,
        description="Name to search for. Omit to browse.",
    ),
    source: List[str] = Query(
        default=[],
        description=(
            "Source(s) to filter by: gadm, kba, wdpa (protectedareas), "
            "landmark, custom. Repeatable; omit to search all sources."
        ),
    ),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=MAX_SEARCH_OFFSET),
    mode: Literal["search", "autocomplete"] = Query(
        default="search",
        description=(
            "search resolves a place name; autocomplete completes what has "
            "been typed so far (at least 2 characters, no offset)."
        ),
    ),
    user: UserModel = Depends(require_auth),
):
    """Search/browse AOIs by name and source type.

    - Provide ``name`` (at most 200 characters) to search. ``mode=search`` (the default) resolves a
      place name, "Place" or "Place, Parent": exact names and name variants
      first, then partial matches, with a typo correction when nothing
      matches as typed. ``mode=autocomplete`` completes a keystroke: names
      that start with the typed text, or the typed words with the last one
      as a prefix. Both rank prominent places (countries, then states, then
      districts) first and return the rank as ``score``.
    - Omit ``name`` to browse AOIs alphabetically within the selected
      source(s). A browse orders by name, source and source ID.
    - ``source`` may be repeated to search several sources at once; omitting
      it searches all available sources. Aliases such as ``protectedareas``
      are accepted.

    A custom area appears only if the caller owns it. Disputed and deprecated
    AOIs never appear, which hides the GADM rows for disputed territories.
    Use ``GET /api/geometry/{source}/{src_id}`` to read one of those by ID.

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
            mode=mode,
        )
    except SearchRequestError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    rows = df.to_dict(orient="records")
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]
        response.headers["X-Next-Offset"] = str(offset + limit)

    return [
        AOISearchResult(**row, score=row.get("similarity_score"))
        for row in rows
    ]
