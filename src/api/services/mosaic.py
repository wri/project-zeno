"""Sentinel-2 mosaic creation shared by the API router and the agent tool.

Searches the earth-search STAC API for Sentinel-2 L2A scenes (COGs hosted in
the public sentinel-cogs AWS bucket) around a target date and builds a
MosaicJSON.

Mosaics are not persisted: the mosaic id handed to clients is a signed token
encoding the build recipe (AOI references, target date, search parameters).
The in-memory store is only a per-process cache — on a cache miss the
ensure_mosaic route dependency rebuilds the mosaic from its token, so any
previously issued mosaic URL keeps working across restarts, workers and
replicas. Signing (itsdangerous) prevents outsiders from crafting tokens for
the unauthenticated tile endpoints.
"""

import asyncio
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
from itsdangerous import BadSignature, URLSafeSerializer
from pyproj import Geod
from shapely import union_all
from shapely.geometry import mapping, shape

from src.api.config import APISettings
from src.shared.geocoding_helpers import get_geometry_data
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

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
    window_days: int = 30
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


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(APISettings.mosaic_token_secret, salt="mosaic")


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
    return _serializer().dumps(payload)


def decode_recipe(token: str) -> MosaicRecipe:
    """Decode and verify a mosaic token; raise MosaicNotFoundError if bad."""
    try:
        payload = _serializer().loads(token)
        return MosaicRecipe(
            aois=tuple((source, src_id) for source, src_id in payload["a"]),
            target_date=date.fromisoformat(payload["d"]),
            window_days=payload["w"],
            max_cloud_cover=payload["c"],
            max_items=payload["n"],
            user_id=payload.get("u"),
        )
    except (BadSignature, KeyError, ValueError, TypeError):
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
            abs((item.datetime.date() - recipe.target_date).days),
            item.properties.get("eo:cloud_cover", 100),
        )
    )

    mosaic = MosaicJSON.from_features(
        [item.to_dict() for item in items],
        minzoom=8,
        maxzoom=14,
        accessor=lambda f: f["assets"][VISUAL_ASSET]["href"],
    )

    token = encode_recipe(recipe)
    _mosaic_store[token] = mosaic
    logger.info("Mosaic created", item_count=len(items))

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
                await create_sentinel2_mosaic(recipe)
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
