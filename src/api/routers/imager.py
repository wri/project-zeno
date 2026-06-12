"""Sentinel-2 mosaic tile service over AOI geometries.

The tile/tilejson endpoints from the titiler factory are unauthenticated so
plain map clients can load tiles; mosaic ids are unguessable UUIDs and only
creation requires auth.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from titiler.mosaic.factory import MosaicTilerFactory

from src.api.auth.dependencies import require_auth
from src.api.schemas import UserModel
from src.api.services.mosaic import (
    AoiTooLargeError,
    InMemoryBackend,
    NoScenesFoundError,
    StacSearchError,
    create_sentinel2_mosaic,
)
from src.shared.geocoding_helpers import get_geometry_data
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

_mosaic_tiler = MosaicTilerFactory(backend=InMemoryBackend)

router = APIRouter()
router.include_router(_mosaic_tiler.router)


class MosaicCreateResponse(BaseModel):
    mosaic_id: str
    item_count: int
    date_start: date
    date_end: date


@router.post("/create/{source}/{src_id}", response_model=MosaicCreateResponse)
async def create_mosaic(
    source: str,
    src_id: str,
    target_date: Optional[date] = None,
    window_days: int = Query(30, ge=1, le=183),
    max_cloud_cover: int = Query(20, ge=0, le=100),
    max_items: int = Query(50, ge=1, le=100),
    user: UserModel = Depends(require_auth),
):
    """
    Search Sentinel-2 L2A scenes covering an AOI around target_date
    (within ±window_days) and cache a MosaicJSON.

    Returns a mosaic_id to pass as ?url= to the titiler mosaic endpoints:
      GET /mosaic/tiles/WebMercatorQuad/{z}/{x}/{y}[.{format}]?url={mosaic_id}
      GET /mosaic/WebMercatorQuad/tilejson.json?url={mosaic_id}
    """
    data = await get_geometry_data(source, src_id, user_id=user.id)
    if not data or not data.get("geometry"):
        raise HTTPException(status_code=404, detail="Geometry not found")

    try:
        result = await create_sentinel2_mosaic(
            geometry=data["geometry"],
            target_date=target_date,
            window_days=window_days,
            max_cloud_cover=max_cloud_cover,
            max_items=max_items,
        )
    except AoiTooLargeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except NoScenesFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except StacSearchError:
        raise HTTPException(status_code=502, detail="STAC search failed")
    except Exception as e:
        logger.error("MosaicJSON creation failed", error=str(e))
        raise HTTPException(status_code=500, detail="Mosaic build failed")

    return MosaicCreateResponse(
        mosaic_id=result.mosaic_id,
        item_count=result.item_count,
        date_start=result.date_start,
        date_end=result.date_end,
    )
