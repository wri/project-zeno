"""AOI thumbnail generation via Mapbox Static Images API."""

import json
import urllib.parse

import httpx
import shapely.geometry
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from src.api.auth.dependencies import require_auth
from src.api.config import APISettings
from src.shared.geocoding_helpers import get_geometry_data
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()

_MAPBOX_STYLE = "mapbox/outdoors-v12"
_STROKE_COLOR = "#1b3a6e"
_FILL_COLOR = "#4a90d9"
_FILL_OPACITY = 0.15
# Keep URL-encoded overlay below this to stay well under HTTP URL limits
_MAX_OVERLAY_CHARS = 5000


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


def _simplify(geometry: dict, tolerance: float) -> dict:
    try:
        shape = _filter_small_parts(shapely.geometry.shape(geometry))
        simplified = shape.simplify(tolerance, preserve_topology=True)
        return shapely.geometry.mapping(simplified)
    except Exception:
        return geometry


def _fit_overlay(geometry: dict) -> str:
    """Simplify iteratively until the overlay fits within the URL budget."""
    for tolerance in [0.001, 0.005, 0.01, 0.05, 0.1, 0.5]:
        encoded = _encode_overlay(_simplify(geometry, tolerance))
        if len(encoded) <= _MAX_OVERLAY_CHARS:
            return encoded
    # Last resort: convex hull of the largest part
    try:
        shape = _filter_small_parts(shapely.geometry.shape(geometry))
        hull = shapely.geometry.mapping(shape.convex_hull)
        return _encode_overlay(hull)
    except Exception:
        return _encode_overlay(geometry)


@router.get("/api/geometry/{source}/{src_id}/thumbnail")
async def get_geometry_thumbnail(
    source: str,
    src_id: str,
    width: int = 300,
    height: int = 300,
    user=Depends(require_auth),
):
    """
    Proxy a PNG thumbnail for an AOI via the Mapbox Static Images API.
    The geometry is simplified as needed to stay within URL limits.
    """
    if not APISettings.mapbox_api_token:
        raise HTTPException(
            status_code=503, detail="MAPBOX_TOKEN not configured"
        )

    data = await get_geometry_data(source, src_id)
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
