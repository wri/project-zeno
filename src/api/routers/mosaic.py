"""Sentinel-2 mosaic creation endpoint.

Searches Sentinel-2 L2A scenes for an AOI and builds a MosaicJSON persisted
to S3. Tiles are served externally by the GFW tiles service at
https://tiles.globalforestwatch.org using the s3:// URI returned here.
"""

from datetime import date
from typing import Optional

from cogeo_mosaic.errors import MosaicNotFoundError
from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.auth.dependencies import require_auth
from src.api.models import MosaicCreateResponse
from src.api.schemas import UserModel
from src.api.services.mosaic import (
    AoiTooLargeError,
    MosaicRecipe,
    NoScenesFoundError,
    StacSearchError,
    create_sentinel2_mosaic,
)
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.post("/create/{source}/{src_id}", response_model=MosaicCreateResponse)
async def create_mosaic(
    source: str,
    src_id: str,
    target_date: Optional[date] = None,
    window_days: int = Query(7, ge=1, le=183),
    max_cloud_cover: int = Query(20, ge=0, le=100),
    max_items: int = Query(50, ge=1, le=100),
    user: UserModel = Depends(require_auth),
):
    """
    Search Sentinel-2 L2A scenes covering an AOI around target_date
    (within ±window_days) and persist a MosaicJSON to S3.

    Returns a mosaic_id (recipe token). Tile and TileJSON URLs pointing to
    the GFW tiles service are available on the result (tile_url / tilejson_url).
    """
    recipe = MosaicRecipe(
        aois=((source, src_id),),
        target_date=target_date or date.today(),
        window_days=window_days,
        max_cloud_cover=max_cloud_cover,
        max_items=max_items,
        user_id=user.id if source == "custom" else None,
    )

    try:
        result = await create_sentinel2_mosaic(recipe)
    except MosaicNotFoundError:
        raise HTTPException(status_code=404, detail="Geometry not found")
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
