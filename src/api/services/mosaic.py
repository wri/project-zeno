"""Sentinel-2 mosaic creation shared by the API router and the agent tool.

Searches the earth-search STAC API for Sentinel-2 L2A scenes (COGs hosted in
the public sentinel-cogs AWS bucket) around a target date and builds a
MosaicJSON.

The built MosaicJSON is written to a private S3 bucket under a key derived
from a deterministic, self-describing recipe token (AOI references, target
date, search parameters). Tiles are served by an external, vanilla titiler
deployment that reads the MosaicJSON from S3 via ``s3://`` using IAM
credentials — this repo no longer serves tiles itself.

Before building, we look up the recipe token in S3: if a mosaic already
exists we skip the (expensive) STAC search, build and upload, and return the
metadata recorded in a small sidecar object written alongside the mosaic.
"""

import base64
import functools
import json
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional
from urllib.parse import quote

import boto3
import pystac_client
from botocore.exceptions import ClientError
from cogeo_mosaic.errors import MosaicNotFoundError
from cogeo_mosaic.mosaic import MosaicJSON
from fastapi.concurrency import run_in_threadpool
from pyproj import Geod
from shapely import union_all
from shapely.geometry import mapping, shape

from src.shared.config import SharedSettings
from src.shared.geocoding_helpers import get_geometry_data
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

STAC_URL = "https://earth-search.aws.element84.com/v1"
SENTINEL2_COLLECTION = "sentinel-2-l2a"
VISUAL_ASSET = "visual"

# Mosaics are meant for regional AOIs; mid-size countries exceed this.
MAX_AOI_AREA_KM2 = 50_000

_geod = Geod(ellps="WGS84")


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


# ---------------------------------------------------------------------------
# S3 persistence
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def _s3_client():
    return boto3.client(
        "s3", region_name=SharedSettings.mosaic_s3_region or None
    )


def _s3_key(token: str) -> str:
    return f"{SharedSettings.mosaic_s3_prefix.strip('/')}/{token}.json"


def _meta_key(token: str) -> str:
    return f"{SharedSettings.mosaic_s3_prefix.strip('/')}/{token}.meta.json"


def _s3_uri(token: str) -> str:
    return f"s3://{SharedSettings.mosaic_s3_bucket}/{_s3_key(token)}"


def _read_meta(token: str) -> Optional[dict]:
    """Return the mosaic's metadata sidecar, or None if it does not exist.

    The sidecar is written last, so its presence implies the mosaic object
    itself is fully written.
    """
    try:
        resp = _s3_client().get_object(
            Bucket=SharedSettings.mosaic_s3_bucket, Key=_meta_key(token)
        )
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404", "NotFound"):
            return None
        raise
    return json.loads(resp["Body"].read())


def _write_mosaic(
    token: str,
    mosaic: MosaicJSON,
    item_count: int,
    date_start: date,
    date_end: date,
) -> None:
    """Upload the MosaicJSON and its metadata sidecar to S3.

    The mosaic object is written first, then the sidecar, so a present
    sidecar always implies a complete mosaic.
    """
    client = _s3_client()
    bucket = SharedSettings.mosaic_s3_bucket
    client.put_object(
        Bucket=bucket,
        Key=_s3_key(token),
        Body=mosaic.model_dump_json(exclude_none=True).encode("utf-8"),
        ContentType="application/json",
    )
    client.put_object(
        Bucket=bucket,
        Key=_meta_key(token),
        Body=json.dumps(
            {
                "item_count": item_count,
                "date_start": date_start.isoformat(),
                "date_end": date_end.isoformat(),
            }
        ).encode("utf-8"),
        ContentType="application/json",
    )


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
        base = SharedSettings.mosaic_tiler_url.rstrip("/")
        url = quote(_s3_uri(self.mosaic_id), safe="")
        return (
            f"{base}/mosaic/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}.png"
            f"?url={url}"
        )

    @property
    def tilejson_url(self) -> str:
        base = SharedSettings.mosaic_tiler_url.rstrip("/")
        url = quote(_s3_uri(self.mosaic_id), safe="")
        return f"{base}/mosaic/WebMercatorQuad/tilejson.json?url={url}"


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
    """Build the mosaic for a recipe and persist it to S3.

    If a mosaic for this recipe already exists in S3, the STAC search, build
    and upload are skipped and the recorded metadata is returned.

    Raises MosaicNotFoundError (AOI geometry gone), AoiTooLargeError,
    StacSearchError or NoScenesFoundError.
    """
    token = encode_recipe(recipe)

    # S3-based lookup: if the mosaic already exists, return without rebuilding.
    meta = await run_in_threadpool(_read_meta, token)
    if meta is not None:
        return MosaicResult(
            mosaic_id=token,
            item_count=meta["item_count"],
            date_start=date.fromisoformat(meta["date_start"]),
            date_end=date.fromisoformat(meta["date_end"]),
        )

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

    item_dates = [item.datetime.date() for item in items]
    date_start = min(item_dates)
    date_end = max(item_dates)

    await run_in_threadpool(
        _write_mosaic, token, mosaic, len(items), date_start, date_end
    )
    logger.info(
        "Mosaic created",
        item_count=len(items),
        build_ms=round((time.perf_counter() - build_start) * 1000),
    )

    return MosaicResult(
        mosaic_id=token,
        item_count=len(items),
        date_start=date_start,
        date_end=date_end,
    )
