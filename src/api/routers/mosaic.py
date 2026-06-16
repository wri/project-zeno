"""Sentinel-2 mosaic creation and tile serving over AOI geometries.

The create endpoint builds a MosaicJSON, persists it to S3 (see
src/api/services/mosaic.py) and returns a recipe-token mosaic id.

Tiles are served by the titiler MosaicTilerFactory mounted here, wired to
S3MosaicBackend so it reads the persisted MosaicJSON from S3 via the
``s3://`` uri in the tile URL's ``?url=`` param. When MOSAIC_TILER_URL is
set, MosaicResult instead emits absolute URLs to that external titiler and
these in-repo tile routes go unused.

All endpoints — including the titiler tile/tilejson routes — require the
same bearer auth as the rest of the API; map clients must attach the
Authorization header to tile requests.
"""

from datetime import date
from typing import Optional

from cogeo_mosaic.errors import MosaicNotFoundError
from fastapi import APIRouter, Depends, HTTPException, Query
from titiler.mosaic.factory import MosaicTilerFactory

from src.api.auth.dependencies import require_auth
from src.api.models import MosaicCreateResponse
from src.api.schemas import UserModel
from src.api.services.mosaic import (
    AoiTooLargeError,
    MosaicRecipe,
    NoScenesFoundError,
    S3MosaicBackend,
    StacSearchError,
    create_sentinel2_mosaic,
)
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

_mosaic_tiler = MosaicTilerFactory(backend=S3MosaicBackend)

router = APIRouter()
router.include_router(
    _mosaic_tiler.router,
    dependencies=[Depends(require_auth)],
)


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

    Returns a mosaic_id (recipe token). The tile/tilejson URLs that read the
    persisted MosaicJSON from S3 are available on the MosaicResult
    (tile_url / tilejson_url).
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
