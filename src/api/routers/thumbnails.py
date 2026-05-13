"""AOI thumbnail generation via Mapbox Static Images API."""

import json
import urllib.parse

import antimeridian
import httpx
import shapely
import shapely.geometry
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from src.api.auth.dependencies import require_auth
from src.api.config import APISettings
from src.api.schemas import UserModel
from src.shared.geocoding_helpers import get_geometry_data
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()

_MAPBOX_STYLE = "mapbox/outdoors-v12"
_STROKE_COLOR = "#1b3a6e"
_FILL_COLOR = "#4a90d9"
_FILL_OPACITY = 0.15
# Mapbox's documented GeoJSON overlay limit is 8 192 URL-encoded chars.
# We stay comfortably below that to leave room for the rest of the URL.
_MAX_OVERLAY_CHARS = 7500


def _geojson_feature(geometry: dict) -> dict:
    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": {
            "stroke": _STROKE_COLOR,
            "stroke-width": 2,
            "stroke-opacity": 1,
            "fill": _FILL_COLOR,
            "fill-opacity": _FILL_OPACITY,
        },
    }


def _to_feature_collection(geometry: dict) -> dict:
    if geometry["type"] == "GeometryCollection":
        return {
            "type": "FeatureCollection",
            "features": [_geojson_feature(g) for g in geometry["geometries"]],
        }
    return _geojson_feature(geometry)


def _encode_overlay(geometry: dict) -> str:
    return urllib.parse.quote(
        json.dumps(_to_feature_collection(geometry), separators=(",", ":"))
    )


def _filter_small_parts(shape, min_area_fraction: float = 0.005):
    """Drop sub-polygons smaller than min_area_fraction of the total area.

    Keeps complex MultiPolygons (e.g. Brazil) from blowing up the URL with
    hundreds of tiny islands while preserving the main landmass outline.
    """
    if shape.geom_type != "MultiPolygon":
        return shape
    total = shape.area
    parts = [p for p in shape.geoms if p.area / total >= min_area_fraction]
    if not parts:
        parts = [max(shape.geoms, key=lambda p: p.area)]
    return shapely.geometry.MultiPolygon(parts) if len(parts) > 1 else parts[0]


def _drop_interior_rings(shape):
    """Remove interior rings (holes) from polygons.

    For overlay thumbnails we only care about the outer outline. Interior
    rings from lakes/water-bodies inflate the encoded size significantly
    (Russia's main polygon has 80 holes) without adding visual value at the
    zoom levels used for thumbnails.
    """
    if shape.geom_type == "Polygon":
        return shapely.geometry.Polygon(shape.exterior)
    if shape.geom_type == "MultiPolygon":
        parts = [
            shapely.geometry.Polygon(p.exterior)
            for p in shape.geoms
            if not p.is_empty
        ]
        return (
            shapely.geometry.MultiPolygon(parts)
            if len(parts) > 1
            else parts[0]
        )
    return shape


def _fix_shape(geometry: dict) -> dict:
    """Run antimeridian.fix_shape, falling back to the original on failure.

    Some real-world geometries (e.g. KBAs with degenerate rings that have
    fewer than 4 coordinates) cause fix_shape to crash.  Rather than
    propagating the error we silently skip the fix — the geometry will still
    simplify correctly; it just may not be split at the antimeridian.
    """
    try:
        return antimeridian.fix_shape(geometry)
    except Exception:
        return geometry


def _prepare_shape(geometry: dict):
    """Filter, antimeridian-fix, and drop interior rings — the expensive
    one-time work before the tolerance sweep.  Returns a shapely geometry,
    or the original dict on failure.
    """
    try:
        # Filter first: fix_shape only processes the few large parts, not
        # thousands of tiny islands (avoids minute-long hangs on USA/RUS).
        shape = _filter_small_parts(shapely.geometry.shape(geometry))
        shape = shapely.geometry.shape(
            _fix_shape(shapely.geometry.mapping(shape))
        )
        return _drop_interior_rings(shape)
    except Exception:
        return None


def _round_coords(geometry: dict, decimals: int = 4) -> dict:
    """Round all coordinate floats to ``decimals`` decimal places.

    ``shapely.set_precision`` snaps to a grid but produces floats like
    47.930000000000004 that JSON serialises to 18 chars.  Explicit rounding
    gives 47.93 (5 chars) — a 3× reduction that lets lower (smoother)
    simplification tolerances fit within the URL budget.
    """

    def walk(obj):
        if isinstance(obj, (int, float)):
            return round(float(obj), decimals)
        if isinstance(obj, (list, tuple)):
            return [walk(item) for item in obj]
        return obj

    if "coordinates" in geometry:
        return {**geometry, "coordinates": walk(geometry["coordinates"])}
    if "geometries" in geometry:
        return {
            **geometry,
            "geometries": [
                _round_coords(g, decimals) for g in geometry["geometries"]
            ],
        }
    return geometry


def _simplify_shape(shape, tolerance: float) -> dict:
    """Simplify, drop empty parts, round coords, return a geometry dict."""
    s = shape.simplify(tolerance, preserve_topology=True)
    if s.geom_type == "MultiPolygon":
        parts = [g for g in s.geoms if not g.is_empty]
        if parts:
            s = (
                shapely.geometry.MultiPolygon(parts)
                if len(parts) > 1
                else parts[0]
            )
    return _round_coords(shapely.geometry.mapping(s))


def _fit_overlay(geometry: dict) -> str:
    """Simplify iteratively until the overlay fits within the URL budget.

    The expensive preprocessing (filter, antimeridian fix, interior-ring
    removal) runs once; only the cheap simplify + coord-round iterates.
    """
    shape = _prepare_shape(geometry)
    if shape is not None:
        for tolerance in [0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 2.0]:
            try:
                encoded = _encode_overlay(_simplify_shape(shape, tolerance))
                if len(encoded) <= _MAX_OVERLAY_CHARS:
                    return encoded
            except Exception:
                pass
    # Absolute last resort: bounding-box rectangle of the prepared shape
    try:
        s = (
            shape
            if shape is not None
            else _filter_small_parts(shapely.geometry.shape(geometry))
        )
        return _encode_overlay(
            shapely.geometry.mapping(shapely.geometry.box(*s.bounds))
        )
    except Exception:
        return _encode_overlay(geometry)


@router.get("/api/geometry/{source}/{src_id}/thumbnail")
async def get_geometry_thumbnail(
    source: str,
    src_id: str,
    width: int = 300,
    height: int = 300,
    user: UserModel = Depends(require_auth),
):
    """
    Proxy a PNG thumbnail for an AOI via the Mapbox Static Images API.
    The geometry is simplified as needed to stay within URL limits.
    """
    if not APISettings.mapbox_api_token:
        raise HTTPException(
            status_code=503, detail="MAPBOX_TOKEN not configured"
        )

    data = await get_geometry_data(source, src_id, user_id=user.id)
    if not data or not data.get("geometry"):
        raise HTTPException(status_code=404, detail="Geometry not found")

    overlay = _fit_overlay(data["geometry"])
    url = (
        f"https://api.mapbox.com/styles/v1/{_MAPBOX_STYLE}/static"
        f"/geojson({overlay})/auto/{width}x{height}@2x"
        f"?padding=40&attribution=false&logo=false&access_token={APISettings.mapbox_api_token}"
    )

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, timeout=10.0)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error(
                "Mapbox API error",
                status=e.response.status_code,
                body=e.response.text[:200],
            )
            raise HTTPException(
                status_code=502, detail="Thumbnail generation failed"
            )
        except httpx.RequestError as e:
            logger.error("Mapbox request error", error=str(e))
            raise HTTPException(
                status_code=502, detail="Thumbnail generation failed"
            )

    return Response(
        content=resp.content,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )
