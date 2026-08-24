"""Geometry lookup endpoint."""

from fastapi import APIRouter, Depends, HTTPException

from src.api.auth.dependencies import require_auth
from src.api.schemas import GeometryResponse, UserModel
from src.shared.geocoding_helpers import get_geometry_data
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("/api/geometry/{source}/{src_id}", response_model=GeometryResponse)
async def get_geometry(
    source: str,
    src_id: str,
    user: UserModel = Depends(require_auth),
):
    """Return the geometry of one AOI, found by source and source ID.

    A reference source (``gadm``, ``kba``, ``wdpa``, ``landmark``) reads the
    unified ``aois`` table and returns a ``MultiPolygon``. A ``custom`` area
    reads ``custom_areas`` and returns the drawn geometry unchanged: a
    ``Polygon`` for one part, or a ``GeometryCollection`` for two or more.

    This endpoint finds an AOI by its ID, so it includes disputed areas.
    ``GET /api/aois`` excludes them. This endpoint also does not accept the
    source aliases that ``GET /api/aois`` accepts. Send ``wdpa``, and not
    ``protectedareas``.

    It returns 404 if no AOI has that ID, and 400 for an unknown source.

    Examples:

    - ``GET /api/geometry/gadm/IND.26.2_1``
    - ``GET /api/geometry/kba/16595``
    - ``GET /api/geometry/custom/123e4567-e89b-12d3-a456-426614174000``
    """
    try:
        result = await get_geometry_data(source, src_id)

        if not result:
            raise HTTPException(
                status_code=404,
                detail=f"Geometry not found for source '{source}' with ID {src_id}",
            )

        return GeometryResponse(**result)

    except ValueError as e:
        logger.exception(f"Error fetching geometry for {source}:{src_id}")
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching geometry for {source}:{src_id}")
        raise HTTPException(status_code=500, detail=str(e))
