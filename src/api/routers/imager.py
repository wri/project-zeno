"""Sentinel-2 mosaic tile service over AOI geometries."""

import uuid
from datetime import date
from typing import Optional

import attr
import pystac_client
from cachetools import TTLCache
from cogeo_mosaic.backends.base import BaseBackend
from cogeo_mosaic.errors import MosaicNotFoundError
from cogeo_mosaic.mosaic import MosaicJSON
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from pyproj import Geod
from shapely.geometry import shape
from titiler.mosaic.factory import MosaicTilerFactory

from src.api.auth.dependencies import require_auth
from src.api.schemas import UserModel
from src.shared.geocoding_helpers import get_geometry_data
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

_STAC_URL = "https://earth-search.aws.element84.com/v1"
_SENTINEL2_COLLECTION = "sentinel-2-l2a"
_VISUAL_ASSET = "visual"

# Mosaics are meant for regional AOIs; mid-size countries exceed this.
_MAX_AOI_AREA_KM2 = 50_000

_geod = Geod(ellps="WGS84")


def check_aoi_area(geometry: dict) -> float:
    """Return the geodesic area of a GeoJSON geometry in km², or raise 422."""
    area_km2 = abs(_geod.geometry_area_perimeter(shape(geometry))[0]) / 1e6
    if area_km2 > _MAX_AOI_AREA_KM2:
        raise HTTPException(
            status_code=422,
            detail=(
                f"AOI is too large for satellite imagery mosaics "
                f"({area_km2:,.0f} km²; limit {_MAX_AOI_AREA_KM2:,} km²). "
                "Choose a smaller, regional area."
            ),
        )
    return area_km2


# mosaic_id → MosaicJSON. In-memory and per-process: mosaics expire after the
# TTL and are not shared across workers/replicas — swap for Redis/DB if the
# API ever runs with more than one process.
_mosaic_store: TTLCache = TTLCache(maxsize=256, ttl=12 * 3600)


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
    max_cloud_cover: int = Query(20, ge=0, le=100),
    max_items: int = Query(50, ge=1, le=100),
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

    check_aoi_area(data["geometry"])

    def _search() -> list:
        catalog = pystac_client.Client.open(_STAC_URL)
        search = catalog.search(
            collections=[_SENTINEL2_COLLECTION],
            intersects=data["geometry"],
            datetime=f"{actual_start}/{actual_end}",
            query={"eo:cloud_cover": {"lt": max_cloud_cover}},
            max_items=max_items,
        )
        return list(search.items())

    try:
        # pystac_client is synchronous; keep it off the event loop.
        items = await run_in_threadpool(_search)
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
