"""Sentinel-2 mosaic creation shared by the API router and the agent tool.

Searches the earth-search STAC API for Sentinel-2 L2A scenes (COGs hosted in
the public sentinel-cogs AWS bucket) around a target date, builds a MosaicJSON
and caches it in memory under a mosaic id that the titiler mosaic endpoints
resolve via ``?url={mosaic_id}``.
"""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import attr
import pystac_client
from cachetools import TTLCache
from cogeo_mosaic.backends.base import BaseBackend
from cogeo_mosaic.errors import MosaicNotFoundError
from cogeo_mosaic.mosaic import MosaicJSON
from fastapi.concurrency import run_in_threadpool
from pyproj import Geod
from shapely.geometry import shape

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

STAC_URL = "https://earth-search.aws.element84.com/v1"
SENTINEL2_COLLECTION = "sentinel-2-l2a"
VISUAL_ASSET = "visual"

# Mosaics are meant for regional AOIs; mid-size countries exceed this.
MAX_AOI_AREA_KM2 = 50_000

_geod = Geod(ellps="WGS84")

# mosaic_id → MosaicJSON. In-memory and per-process: mosaics expire after the
# TTL and are not shared across workers/replicas — swap for Redis/DB if the
# API ever runs with more than one process.
_mosaic_store: TTLCache = TTLCache(maxsize=256, ttl=12 * 3600)


class AoiTooLargeError(Exception):
    def __init__(self, area_km2: float):
        self.area_km2 = area_km2
        super().__init__(
            f"AOI is too large for satellite imagery mosaics "
            f"({area_km2:,.0f} km²; limit {MAX_AOI_AREA_KM2:,} km²). "
            "Choose a smaller, regional area."
        )


class StacSearchError(Exception):
    pass


class NoScenesFoundError(Exception):
    pass


@attr.s
class InMemoryBackend(BaseBackend):
    """Resolve a mosaic by ID from the module-level _mosaic_store."""

    _backend_name = "InMemory"

    def _read(self) -> MosaicJSON:
        mosaic = _mosaic_store.get(self.input)
        if mosaic is None:
            raise MosaicNotFoundError(f"Mosaic '{self.input}' not found")
        return mosaic

    def write(self, overwrite: bool = False) -> None:
        pass


@dataclass
class MosaicResult:
    mosaic_id: str
    item_count: int
    date_start: date
    date_end: date

    @property
    def tile_url(self) -> str:
        return (
            "/mosaic/tiles/WebMercatorQuad/{z}/{x}/{y}.png"
            f"?url={self.mosaic_id}"
        )

    @property
    def tilejson_url(self) -> str:
        return f"/mosaic/WebMercatorQuad/tilejson.json?url={self.mosaic_id}"


def check_aoi_area(geometry: dict) -> float:
    """Return the geodesic area of a GeoJSON geometry in km².

    Raises AoiTooLargeError above MAX_AOI_AREA_KM2.
    """
    area_km2 = abs(_geod.geometry_area_perimeter(shape(geometry))[0]) / 1e6
    if area_km2 > MAX_AOI_AREA_KM2:
        raise AoiTooLargeError(area_km2)
    return area_km2


async def create_sentinel2_mosaic(
    geometry: dict,
    target_date: Optional[date] = None,
    window_days: int = 30,
    max_cloud_cover: int = 20,
    max_items: int = 50,
) -> MosaicResult:
    """Search Sentinel-2 scenes around target_date and cache a MosaicJSON.

    Raises AoiTooLargeError, StacSearchError or NoScenesFoundError.
    """
    check_aoi_area(geometry)

    actual_target = target_date or date.today()
    actual_start = actual_target - timedelta(days=window_days)
    actual_end = min(actual_target + timedelta(days=window_days), date.today())

    def _search() -> list:
        catalog = pystac_client.Client.open(STAC_URL)
        search = catalog.search(
            collections=[SENTINEL2_COLLECTION],
            intersects=geometry,
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
        raise StacSearchError("STAC search failed") from e

    if not items:
        raise NoScenesFoundError(
            "No Sentinel-2 scenes found for this AOI and date range"
        )

    # The mosaic renders the first valid scene per tile, so order items by
    # proximity to the target date (cloud cover as tiebreak) to keep the
    # displayed imagery as close to the requested date as possible.
    items.sort(
        key=lambda item: (
            abs((item.datetime.date() - actual_target).days),
            item.properties.get("eo:cloud_cover", 100),
        )
    )

    mosaic = MosaicJSON.from_features(
        [item.to_dict() for item in items],
        minzoom=8,
        maxzoom=14,
        accessor=lambda f: f["assets"][VISUAL_ASSET]["href"],
    )

    mosaic_id = uuid.uuid4().hex
    _mosaic_store[mosaic_id] = mosaic
    logger.info("Mosaic created", mosaic_id=mosaic_id, item_count=len(items))

    item_dates = [item.datetime.date() for item in items]
    return MosaicResult(
        mosaic_id=mosaic_id,
        item_count=len(items),
        date_start=min(item_dates),
        date_end=max(item_dates),
    )
