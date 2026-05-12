"""AOI thumbnail generation via Mapbox Static Images API."""

import json
import urllib.parse

import httpx
import shapely
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


def _drop_empty_parts(shape):
    """Remove empty sub-geometries left behind after simplification."""
    if shape.geom_type != "MultiPolygon":
        return shape
    parts = [g for g in shape.geoms if not g.is_empty]
    if not parts:
        parts = [max(shape.geoms, key=lambda g: g.area)]
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


def _crosses_antimeridian(shape) -> bool:
    """True when the shape has vertices on both sides of the ±180° line."""
    minx, _, maxx, _ = shape.bounds
    return minx < -90 and maxx > 90


def _strip_antimeridian_spillover(shape):
    """For MultiPolygons that span the antimeridian, drop the sub-polygons
    that are on the minority side (area-wise).

    GADM stores antimeridian-crossing countries as two groups: a large group
    on the dominant side (e.g. Russia 19°–180°E) and a small group on the
    other side (e.g. Chukotka tip −180°–−169°W).  Keeping only the dominant
    group produces a clean, non-crossing geometry that Mapbox's ``auto``
    camera handles perfectly.
    """
    if not _crosses_antimeridian(shape):
        return shape
    if shape.geom_type != "MultiPolygon":
        return shape

    positive = [p for p in shape.geoms if p.centroid.x >= 0]
    negative = [p for p in shape.geoms if p.centroid.x < 0]

    pos_area = sum(p.area for p in positive)
    neg_area = sum(p.area for p in negative)

    keep = positive if pos_area >= neg_area else negative
    if not keep:
        return shape
    return shapely.geometry.MultiPolygon(keep) if len(keep) > 1 else keep[0]


def _round_coords(geometry: dict, decimals: int = 4) -> dict:
    """Round all coordinate values to reduce URL-encoded size.

    4 decimal places ≈ 11 m precision — invisible at thumbnail scale but cuts
    each coordinate string from ~18 chars to ~6, allowing lower (smoother)
    simplification tolerances to fit within the URL budget.
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


def _simplify(geometry: dict, tolerance: float) -> dict:
    try:
        shape = _filter_small_parts(shapely.geometry.shape(geometry))
        shape = _strip_antimeridian_spillover(shape)
        simplified = _drop_empty_parts(
            shape.simplify(tolerance, preserve_topology=True)
        )
        return _round_coords(
            shapely.geometry.mapping(_drop_interior_rings(simplified))
        )
    except Exception:
        return geometry


def _fit_overlay(geometry: dict) -> str:
    """Simplify iteratively until the overlay fits within the URL budget."""
    for tolerance in [0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 2.0]:
        encoded = _encode_overlay(_simplify(geometry, tolerance))
        if len(encoded) <= _MAX_OVERLAY_CHARS:
            return encoded
    # Absolute last resort: bounding-box rectangle of the largest part
    try:
        shape = _strip_antimeridian_spillover(
            _filter_small_parts(shapely.geometry.shape(geometry))
        )
        return _encode_overlay(
            shapely.geometry.mapping(shapely.geometry.box(*shape.bounds))
        )
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
