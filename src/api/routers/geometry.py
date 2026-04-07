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
    """
    Get geometry data by source and source ID.

    Args:
        source: Source type (gadm, kba, landmark, wdpa, custom)
        src_id: Source-specific ID (GID_X for GADM, sitrecid for KBA, UUID for custom areas, etc.)

    Example:
        GET /api/geometry/gadm/IND.26.2_1
        GET /api/geometry/kba/16595
        GET /api/geometry/custom/123e4567-e89b-12d3-a456-426614174000
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
