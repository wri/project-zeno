"""Sentinel-2 mosaic creation shared by the API router and the agent tool.

Searches the earth-search STAC API for Sentinel-2 L2A scenes (COGs hosted in
the public sentinel-cogs AWS bucket) around a target date and builds a
MosaicJSON.

Mosaics are not persisted: the mosaic id handed to clients is a token
encoding the build recipe (AOI references, target date, search parameters).
The in-memory store is only a per-process cache — on a cache miss the
ensure_mosaic route dependency rebuilds the mosaic from its token, so any
previously issued mosaic URL keeps working across restarts, workers and
replicas. The tile endpoints require the same bearer auth as the rest of
the API, so the token needs no signature: crafting one grants nothing the
authenticated create endpoint would not.
"""

import asyncio
import base64
import json
import os
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import attr
import pystac_client
from cachetools import TTLCache
from cogeo_mosaic.backends.base import BaseBackend
from cogeo_mosaic.errors import MosaicNotFoundError
from cogeo_mosaic.mosaic import MosaicJSON
from fastapi import HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pyproj import Geod
from shapely import union_all
from shapely.geometry import mapping, shape

from src.shared.geocoding_helpers import get_geometry_data
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

# GDAL tuning for reading remote COGs (read by rasterio at open time, so
# deployment env vars take precedence). Without GDAL_DISABLE_READDIR_ON_OPEN
# every COG open issues extra (404ing) sidecar-file requests against S3.
_GDAL_ENV_DEFAULTS = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "GDAL_HTTP_MULTIPLEX": "YES",
    "GDAL_HTTP_VERSION": "2",
    "GDAL_CACHEMAX": "200",
    "VSI_CACHE": "TRUE",
    "VSI_CACHE_SIZE": "5000000",
    "CPL_VSIL_CURL_CACHE_SIZE": "200000000",
    # Sentinel-2 COG headers are larger than GDAL's 16KB default read.
    "GDAL_INGESTED_BYTES_AT_OPEN": "32768",
}
for _key, _value in _GDAL_ENV_DEFAULTS.items():
    os.environ.setdefault(_key, _value)

STAC_URL = "https://earth-search.aws.element84.com/v1"
SENTINEL2_COLLECTION = "sentinel-2-l2a"
VISUAL_ASSET = "visual"

# Mosaics are meant for regional AOIs; mid-size countries exceed this.
MAX_AOI_AREA_KM2 = 50_000

_geod = Geod(ellps="WGS84")

# token → MosaicJSON. Pure per-process cache; misses are rebuilt from the
# token by ensure_mosaic.
_mosaic_store: TTLCache = TTLCache(maxsize=256, ttl=12 * 3600)

# token → lock, so concurrent tile requests trigger at most one rebuild.
_rebuild_locks: dict[str, asyncio.Lock] = {}


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
    """Resolve a mosaic by token from the module-level _mosaic_store."""

    _backend_name = "InMemory"

    def _read(self) -> MosaicJSON:
        mosaic = _mosaic_store.get(self.input)
        if mosaic is None:
            raise MosaicNotFoundError("Mosaic not found")
        return mosaic

    def tile(self, *args, **kwargs):
        # Read scenes sequentially with lazy early exit: with the default
        # "first" pixel selection, reading stops as soon as the tile is
        # covered. The factory default (threads=70) would instead fetch
        # every candidate scene from S3 concurrently and discard most.
        kwargs["threads"] = 0
        return super().tile(*args, **kwargs)

    def write(self, overwrite: bool = False) -> None:
        pass


@dataclass(frozen=True)
class MosaicRecipe:
    """Everything needed to (re)build a mosaic deterministically.

    target_date is always a resolved date, never an implicit "today", so a
    token rebuilt later yields the same imagery. user_id is only set when a
    custom area is referenced (its geometry lookup is scoped to the owner).
    """

    aois: tuple[tuple[str, str], ...]  # (source, src_id) pairs
    target_date: date
    window_days: int = 7
    max_cloud_cover: int = 20
    max_items: int = 50
    user_id: Optional[str] = None


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


def encode_recipe(recipe: MosaicRecipe) -> str:
    payload = {
        "a": [list(pair) for pair in recipe.aois],
        "d": recipe.target_date.isoformat(),
        "w": recipe.window_days,
        "c": recipe.max_cloud_cover,
        "n": recipe.max_items,
    }
    if recipe.user_id:
        payload["u"] = recipe.user_id
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_recipe(token: str) -> MosaicRecipe:
    """Decode a mosaic token; raise MosaicNotFoundError if malformed.

    Parameters are clamped to the same bounds the create endpoint
    enforces, since tokens are plain encodings anyone could construct.
    """
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        payload = json.loads(raw)
        return MosaicRecipe(
            aois=tuple((source, src_id) for source, src_id in payload["a"]),
            target_date=date.fromisoformat(payload["d"]),
            window_days=max(1, min(int(payload["w"]), 183)),
            max_cloud_cover=max(1, min(int(payload["c"]), 100)),
            max_items=max(1, min(int(payload["n"]), 100)),
            user_id=payload.get("u"),
        )
    except (KeyError, ValueError, TypeError):
        raise MosaicNotFoundError("Invalid mosaic token")


def check_aoi_area(geometry: dict) -> float:
    """Return the geodesic area of a GeoJSON geometry in km².

    Raises AoiTooLargeError above MAX_AOI_AREA_KM2.
    """
    area_km2 = abs(_geod.geometry_area_perimeter(shape(geometry))[0]) / 1e6
    if area_km2 > MAX_AOI_AREA_KM2:
        raise AoiTooLargeError(area_km2)
    return area_km2


async def _load_geometry(recipe: MosaicRecipe) -> dict:
    """Union the geometries of the recipe's AOIs into one GeoJSON geometry."""
    shapes = []
    for source, src_id in recipe.aois:
        data = await get_geometry_data(source, src_id, user_id=recipe.user_id)
        if data and data.get("geometry"):
            shapes.append(shape(data["geometry"]))
    if not shapes:
        raise MosaicNotFoundError("AOI geometry not found")
    return mapping(union_all(shapes))


async def create_sentinel2_mosaic(recipe: MosaicRecipe) -> MosaicResult:
    """Build the mosaic for a recipe and cache it under its token.

    Raises MosaicNotFoundError (AOI geometry gone), AoiTooLargeError,
    StacSearchError or NoScenesFoundError.
    """
    geometry = await _load_geometry(recipe)
    check_aoi_area(geometry)

    actual_start = recipe.target_date - timedelta(days=recipe.window_days)
    actual_end = min(
        recipe.target_date + timedelta(days=recipe.window_days), date.today()
    )

    def _search() -> list:
        catalog = pystac_client.Client.open(STAC_URL)
        search = catalog.search(
            collections=[SENTINEL2_COLLECTION],
            intersects=geometry,
            datetime=f"{actual_start}/{actual_end}",
            query={"eo:cloud_cover": {"lt": recipe.max_cloud_cover}},
            max_items=recipe.max_items,
        )
        return list(search.items())

    search_start = time.perf_counter()
    try:
        # pystac_client is synchronous; keep it off the event loop.
        items = await run_in_threadpool(_search)
    except Exception as e:
        logger.error(
            "STAC search failed",
            error=str(e),
            datetime_range=f"{actual_start}/{actual_end}",
            elapsed_ms=round((time.perf_counter() - search_start) * 1000),
        )
        raise StacSearchError("STAC search failed") from e

    logger.info(
        "STAC search completed",
        item_count=len(items),
        datetime_range=f"{actual_start}/{actual_end}",
        max_cloud_cover=recipe.max_cloud_cover,
        max_items=recipe.max_items,
        elapsed_ms=round((time.perf_counter() - search_start) * 1000),
    )

    if not items:
        raise NoScenesFoundError(
            "No Sentinel-2 scenes found for this AOI and date range"
        )

    # The mosaic renders the first valid scene per tile, so order items by
    # proximity to the target date (cloud cover as tiebreak) to keep the
    # displayed imagery as close to the requested date as possible.
    items.sort(
        key=lambda item: (
            abs((item.datetime.date() - recipe.target_date).days),
            item.properties.get("eo:cloud_cover", 100),
        )
    )

    build_start = time.perf_counter()
    mosaic = MosaicJSON.from_features(
        [item.to_dict() for item in items],
        minzoom=8,
        maxzoom=14,
        accessor=lambda f: f["assets"][VISUAL_ASSET]["href"],
        # Bound the sequential first-match reads per tile; items are sorted
        # by date proximity, so the nearest scenes are kept.
        maximum_items_per_tile=12,
    )

    token = encode_recipe(recipe)
    _mosaic_store[token] = mosaic
    logger.info(
        "Mosaic created",
        item_count=len(items),
        build_ms=round((time.perf_counter() - build_start) * 1000),
    )

    item_dates = [item.datetime.date() for item in items]
    return MosaicResult(
        mosaic_id=token,
        item_count=len(items),
        date_start=min(item_dates),
        date_end=max(item_dates),
    )


async def ensure_mosaic(url: str = Query(...)) -> None:
    """Route dependency: rebuild the mosaic from its token if not cached.

    Runs before the (synchronous) titiler endpoints so the rebuild can use
    the async DB pool for geometry lookups.
    """
    if url in _mosaic_store:
        return

    lock = _rebuild_locks.setdefault(url, asyncio.Lock())
    try:
        async with lock:
            if url in _mosaic_store:
                return
            recipe = decode_recipe(url)
            logger.info("Rebuilding mosaic from token")
            try:
                result = await create_sentinel2_mosaic(recipe)
                # If decoding clamped any parameter, the rebuilt mosaic is
                # stored under the canonical token; alias the requested one
                # so this URL does not rebuild on every request.
                if result.mosaic_id != url:
                    _mosaic_store[url] = _mosaic_store[result.mosaic_id]
            except AoiTooLargeError as e:
                raise HTTPException(status_code=422, detail=str(e))
            except NoScenesFoundError as e:
                raise HTTPException(status_code=404, detail=str(e))
            except StacSearchError:
                raise HTTPException(
                    status_code=502, detail="STAC search failed"
                )
    finally:
        _rebuild_locks.pop(url, None)
