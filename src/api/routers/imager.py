"""Sentinel-2 mosaic tile service over AOI geometries."""

import uuid
from datetime import date
from typing import Optional

import attr
import pystac_client
from cogeo_mosaic.backends.base import BaseBackend
from cogeo_mosaic.errors import MosaicNotFoundError
from cogeo_mosaic.mosaic import MosaicJSON
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from titiler.mosaic.factory import MosaicTilerFactory

from src.api.auth.dependencies import require_auth
from src.api.schemas import UserModel
from src.shared.geocoding_helpers import get_geometry_data
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

_STAC_URL = "https://earth-search.aws.element84.com/v1"
_SENTINEL2_COLLECTION = "sentinel-2-l2a"
_VISUAL_ASSET = "visual"

# mosaic_id → MosaicJSON — in-memory only; swap for Redis/DB in production
_mosaic_store: dict[str, MosaicJSON] = {}


@attr.s
class _InMemoryBackend(BaseBackend):
    """Resolve a mosaic by ID from the module-level _mosaic_store."""

    _backend_name = "InMemory"

    def _read(self) -> MosaicJSON:
        mosaic = _mosaic_store.get(self.input)
        if mosaic is None:
            raise MosaicNotFoundError(f"Mosaic '{self.input}' not found")
        return mosaic

    def write(self, overwrite: bool = False) -> None:
        pass


_mosaic_tiler = MosaicTilerFactory(backend=_InMemoryBackend)

router = APIRouter()
router.include_router(_mosaic_tiler.router)


class MosaicCreateResponse(BaseModel):
    mosaic_id: str
    item_count: int


@router.post("/create/{source}/{src_id}", response_model=MosaicCreateResponse)
async def create_mosaic(
    source: str,
    src_id: str,
    date_start: Optional[date] = None,
    date_end: Optional[date] = None,
    max_cloud_cover: int = 20,
    max_items: int = 50,
    user: UserModel = Depends(require_auth),
):
    """
    Search Sentinel-2 L2A scenes covering an AOI and cache a MosaicJSON.

    Returns a mosaic_id to pass as ?url= to the titiler mosaic endpoints:
      GET /mosaic/tiles/WebMercatorQuad/{z}/{x}/{y}[.{format}]?url={mosaic_id}
      GET /mosaic/WebMercatorQuad/tilejson.json?url={mosaic_id}
    """
    actual_start = date_start or date(2024, 1, 1)
    actual_end = date_end or date.today()

    data = await get_geometry_data(source, src_id, user_id=user.id)
    if not data or not data.get("geometry"):
        raise HTTPException(status_code=404, detail="Geometry not found")

    try:
        catalog = pystac_client.Client.open(_STAC_URL)
        search = catalog.search(
            collections=[_SENTINEL2_COLLECTION],
            intersects=data["geometry"],
            datetime=f"{actual_start}/{actual_end}",
            query={"eo:cloud_cover": {"lt": max_cloud_cover}},
            max_items=max_items,
        )
        items = list(search.items())
    except Exception as e:
        logger.error("STAC search failed", error=str(e))
        raise HTTPException(status_code=502, detail="STAC search failed")

    if not items:
        raise HTTPException(
            status_code=404,
            detail="No Sentinel-2 scenes found for this AOI and date range",
        )

    try:
        mosaic = MosaicJSON.from_features(
            [item.to_dict() for item in items],
            minzoom=8,
            maxzoom=14,
            accessor=lambda f: f["assets"][_VISUAL_ASSET]["href"],
        )
    except Exception as e:
        logger.error("MosaicJSON creation failed", error=str(e))
        raise HTTPException(status_code=500, detail="Mosaic build failed")

    mosaic_id = uuid.uuid4().hex
    _mosaic_store[mosaic_id] = mosaic
    logger.info("Mosaic created", mosaic_id=mosaic_id, item_count=len(items))

    return MosaicCreateResponse(mosaic_id=mosaic_id, item_count=len(items))
