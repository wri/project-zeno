"""Unit and integration tests for the AOI thumbnail endpoint."""

import json
import urllib.parse
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import shapely.geometry

from src.api.routers.thumbnails import (
    _FILL_COLOR,
    _FILL_OPACITY,
    _MAX_OVERLAY_CHARS,
    _STROKE_COLOR,
    _drop_interior_rings,
    _encode_overlay,
    _filter_small_parts,
    _fit_overlay,
    _geojson_feature,
    _prepare_shape,
    _round_coords,
    _simplify_shape,
    _to_feature_collection,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SIMPLE_POLYGON = {
    "type": "Polygon",
    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
}

SIMPLE_POINT = {"type": "Point", "coordinates": [10.0, 20.0]}

GEOMETRY_COLLECTION = {
    "type": "GeometryCollection",
    "geometries": [SIMPLE_POLYGON, SIMPLE_POINT],
}


def _square(
    lon: float, lat: float, size: float = 1.0
) -> shapely.geometry.Polygon:
    return shapely.geometry.Polygon(
        [
            (lon, lat),
            (lon + size, lat),
            (lon + size, lat + size),
            (lon, lat + size),
            (lon, lat),
        ]
    )


# ---------------------------------------------------------------------------
# _geojson_feature
# ---------------------------------------------------------------------------


def test_geojson_feature_structure():
    feat = _geojson_feature(SIMPLE_POLYGON)
    assert feat["type"] == "Feature"
    assert feat["geometry"] == SIMPLE_POLYGON


def test_geojson_feature_styling():
    feat = _geojson_feature(SIMPLE_POLYGON)
    props = feat["properties"]
    assert props["stroke"] == _STROKE_COLOR
    assert props["fill"] == _FILL_COLOR
    assert props["fill-opacity"] == _FILL_OPACITY
    assert props["stroke-width"] == 2
    assert props["stroke-opacity"] == 1


# ---------------------------------------------------------------------------
# _to_feature_collection
# ---------------------------------------------------------------------------


def test_to_feature_collection_plain_geometry():
    result = _to_feature_collection(SIMPLE_POLYGON)
    # Non-GeometryCollection → single Feature, not a FeatureCollection
    assert result["type"] == "Feature"
    assert result["geometry"] == SIMPLE_POLYGON


def test_to_feature_collection_geometry_collection():
    result = _to_feature_collection(GEOMETRY_COLLECTION)
    assert result["type"] == "FeatureCollection"
    assert len(result["features"]) == 2
    geom_types = {f["geometry"]["type"] for f in result["features"]}
    assert geom_types == {"Polygon", "Point"}


def test_to_feature_collection_preserves_styling_in_each_feature():
    result = _to_feature_collection(GEOMETRY_COLLECTION)
    for feat in result["features"]:
        assert feat["properties"]["stroke"] == _STROKE_COLOR


# ---------------------------------------------------------------------------
# _encode_overlay
# ---------------------------------------------------------------------------


def test_encode_overlay_is_url_encoded():
    encoded = _encode_overlay(SIMPLE_POLYGON)
    # Must not contain raw braces (they must be percent-encoded)
    assert "{" not in encoded
    assert "}" not in encoded


def test_encode_overlay_round_trips():
    encoded = _encode_overlay(SIMPLE_POLYGON)
    decoded = json.loads(urllib.parse.unquote(encoded))
    assert decoded["type"] == "Feature"
    assert decoded["geometry"] == SIMPLE_POLYGON


def test_encode_overlay_geometry_collection_becomes_feature_collection():
    encoded = _encode_overlay(GEOMETRY_COLLECTION)
    decoded = json.loads(urllib.parse.unquote(encoded))
    assert decoded["type"] == "FeatureCollection"
    assert len(decoded["features"]) == 2


# ---------------------------------------------------------------------------
# _filter_small_parts
# ---------------------------------------------------------------------------


def test_filter_small_parts_non_multipolygon_unchanged():
    poly = _square(0, 0)
    result = _filter_small_parts(poly)
    assert result is poly


def test_filter_small_parts_drops_tiny_islands():
    big = _square(0, 0, size=10)  # area = 100
    tiny = _square(
        100, 100, size=0.05
    )  # area = 0.0025; fraction ≈ 0.000025 < 0.005
    mp = shapely.geometry.MultiPolygon([big, tiny])
    result = _filter_small_parts(mp)
    # Only the large polygon survives; single survivor is returned as Polygon
    assert result.geom_type == "Polygon"
    assert result.area == pytest.approx(big.area)


def test_filter_small_parts_keeps_large_enough_parts():
    big = _square(0, 0, size=10)  # area = 100
    medium = _square(50, 50, size=1)  # area = 1; fraction ≈ 0.0099 > 0.005
    mp = shapely.geometry.MultiPolygon([big, medium])
    result = _filter_small_parts(mp)
    assert result.geom_type == "MultiPolygon"
    assert len(result.geoms) == 2


def test_filter_small_parts_fallback_keeps_largest():
    """When all parts fall below the threshold, the largest is kept."""
    big = _square(0, 0, size=10)  # area ≈ 100; fraction = 100/101 ≈ 0.99
    medium = _square(50, 50, size=1)  # area = 1;  fraction = 1/101 ≈ 0.0099
    mp = shapely.geometry.MultiPolygon([big, medium])
    # With a threshold of 0.999 nothing qualifies, so the fallback runs
    result = _filter_small_parts(mp, min_area_fraction=0.999)
    assert result.area == pytest.approx(big.area)


def test_filter_small_parts_single_survivor_is_polygon():
    big = _square(0, 0, size=10)
    tiny = _square(100, 100, size=0.01)
    mp = shapely.geometry.MultiPolygon([big, tiny])
    result = _filter_small_parts(mp)
    # A one-element result must be unwrapped to a plain Polygon
    assert result.geom_type == "Polygon"


# ---------------------------------------------------------------------------
# _drop_interior_rings
# ---------------------------------------------------------------------------


def test_drop_interior_rings_removes_holes_from_polygon():
    outer = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
    hole = [(2, 2), (4, 2), (4, 4), (2, 4), (2, 2)]
    poly = shapely.geometry.Polygon(outer, [hole])
    assert len(list(poly.interiors)) == 1
    result = _drop_interior_rings(poly)
    assert result.geom_type == "Polygon"
    assert len(list(result.interiors)) == 0
    assert result.exterior.equals(poly.exterior)


def test_drop_interior_rings_multipolygon():
    outer = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
    hole = [(2, 2), (4, 2), (4, 4), (2, 4), (2, 2)]
    p1 = shapely.geometry.Polygon(outer, [hole])
    p2 = _square(20, 20, size=5)
    mp = shapely.geometry.MultiPolygon([p1, p2])
    result = _drop_interior_rings(mp)
    assert all(len(list(p.interiors)) == 0 for p in result.geoms)


def test_drop_interior_rings_no_holes_unchanged():
    poly = _square(0, 0, size=5)
    result = _drop_interior_rings(poly)
    assert result.exterior.equals(poly.exterior)


# ---------------------------------------------------------------------------
# _prepare_shape / _simplify_shape / _round_coords
# ---------------------------------------------------------------------------


def test_prepare_shape_strips_interior_rings():
    """_prepare_shape must remove holes — they inflate encoded size."""
    outer = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
    hole = [(2, 2), (4, 2), (4, 4), (2, 4), (2, 2)]
    poly_with_hole = shapely.geometry.Polygon(outer, [hole])
    shape = _prepare_shape(shapely.geometry.mapping(poly_with_hole))
    assert shape is not None
    assert len(list(shape.interiors)) == 0


def test_prepare_shape_returns_none_on_bad_geometry():
    shape = _prepare_shape({"type": "NotAType", "coordinates": []})
    assert shape is None


def test_simplify_shape_reduces_vertex_count():
    import math

    n = 100
    coords = [
        (math.cos(2 * math.pi * i / n), math.sin(2 * math.pi * i / n))
        for i in range(n)
    ]
    coords.append(coords[0])
    geom = {"type": "Polygon", "coordinates": [coords]}
    shape = _prepare_shape(geom)
    assert shape is not None
    simplified = _simplify_shape(shape, tolerance=0.1)
    original_verts = len(list(shapely.geometry.shape(geom).exterior.coords))
    simplified_verts = len(
        list(shapely.geometry.shape(simplified).exterior.coords)
    )
    assert simplified_verts < original_verts


def test_round_coords_compacts_floats():
    """round_coords must produce short JSON-serialisable floats."""
    import json

    geom = {
        "type": "Polygon",
        "coordinates": [[[47.93001174926758, 41.300323486328125]]],
    }
    rounded = _round_coords(geom)
    lon = rounded["coordinates"][0][0][0]
    lat = rounded["coordinates"][0][0][1]
    # Must be at most 4 decimal places
    assert lon == round(47.93001174926758, 4)
    assert lat == round(41.300323486328125, 4)
    # JSON representation must be short (≤ 7 chars per number)
    assert len(json.dumps(lon)) <= 7
    assert len(json.dumps(lat)) <= 7


# ---------------------------------------------------------------------------
# _fit_overlay
# ---------------------------------------------------------------------------


def test_fit_overlay_within_char_budget():
    encoded = _fit_overlay(SIMPLE_POLYGON)
    assert len(encoded) <= _MAX_OVERLAY_CHARS


def test_fit_overlay_complex_geometry_within_budget():
    """A MultiPolygon with many parts must still fit in the URL budget."""
    polys = [_square(i * 5, 0, size=1) for i in range(50)]
    mp = shapely.geometry.mapping(shapely.geometry.MultiPolygon(polys))
    encoded = _fit_overlay(mp)
    assert len(encoded) <= _MAX_OVERLAY_CHARS


def _russia_like() -> shapely.geometry.MultiPolygon:
    """Two patches mimicking Russia: main landmass (19°–180°) + Chukotka (−170°–−155°)."""
    main = shapely.geometry.box(19, 41, 180, 82)
    chukotka = shapely.geometry.box(-170, 60, -155, 72)
    return shapely.geometry.MultiPolygon([main, chukotka])


def test_fit_overlay_russia_like_within_budget():
    """Russia-like antimeridian geometry must fit within the URL budget."""
    mp = shapely.geometry.mapping(_russia_like())
    encoded = _fit_overlay(mp)
    assert len(encoded) <= _MAX_OVERLAY_CHARS
    # Overlay must be valid URL-encoded GeoJSON
    decoded = json.loads(urllib.parse.unquote(encoded))
    assert decoded.get("type") in ("Feature", "FeatureCollection")


# ---------------------------------------------------------------------------
# Endpoint: GET /api/geometry/{source}/{src_id}/thumbnail
# ---------------------------------------------------------------------------

_MOCK_GEOMETRY_DATA = {
    "name": "Test Region",
    "source": "gadm",
    "src_id": "IND.2_1",
    "geometry": SIMPLE_POLYGON,
}


def _mapbox_mock(content: bytes = b"\x89PNG\r\n\x1a\n"):
    """Return a mock async httpx client that returns a fake PNG."""
    mock_response = MagicMock()
    mock_response.content = content
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    mock_cls = MagicMock()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_cls, mock_client


@pytest.mark.asyncio
async def test_thumbnail_requires_auth(client):
    response = await client.get("/api/geometry/gadm/IND.2_1/thumbnail")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_thumbnail_503_without_mapbox_token(client, auth_override):
    auth_override("test-user-1")
    with patch("src.api.routers.thumbnails.APISettings") as mock_settings:
        mock_settings.mapbox_api_token = ""
        response = await client.get(
            "/api/geometry/gadm/IND.2_1/thumbnail",
            headers={"Authorization": "Bearer test-token"},
        )
    assert response.status_code == 503
    assert "MAPBOX_TOKEN" in response.json()["detail"]


@pytest.mark.asyncio
async def test_thumbnail_404_when_geometry_missing(client, auth_override):
    auth_override("test-user-1")
    with (
        patch("src.api.routers.thumbnails.APISettings") as mock_settings,
        patch(
            "src.api.routers.thumbnails.get_geometry_data",
            new_callable=AsyncMock,
        ) as mock_get,
    ):
        mock_settings.mapbox_api_token = "pk.test"
        mock_get.return_value = None

        response = await client.get(
            "/api/geometry/gadm/DOES_NOT_EXIST/thumbnail",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 404
    assert "Geometry not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_thumbnail_404_when_geometry_field_absent(client, auth_override):
    auth_override("test-user-1")
    with (
        patch("src.api.routers.thumbnails.APISettings") as mock_settings,
        patch(
            "src.api.routers.thumbnails.get_geometry_data",
            new_callable=AsyncMock,
        ) as mock_get,
    ):
        mock_settings.mapbox_api_token = "pk.test"
        mock_get.return_value = {"name": "Somewhere", "source": "gadm"}

        response = await client.get(
            "/api/geometry/gadm/IND.2_1/thumbnail",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_thumbnail_success_returns_png(client, auth_override):
    auth_override("test-user-1")
    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    mock_cls, _ = _mapbox_mock(content=fake_png)

    with (
        patch("src.api.routers.thumbnails.APISettings") as mock_settings,
        patch(
            "src.api.routers.thumbnails.get_geometry_data",
            new_callable=AsyncMock,
        ) as mock_get,
        patch("src.api.routers.thumbnails.httpx.AsyncClient", mock_cls),
    ):
        mock_settings.mapbox_api_token = "pk.test"
        mock_get.return_value = _MOCK_GEOMETRY_DATA

        response = await client.get(
            "/api/geometry/gadm/IND.2_1/thumbnail",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    assert response.content == fake_png
    assert response.headers["content-type"] == "image/png"


@pytest.mark.asyncio
async def test_thumbnail_cache_control_header(client, auth_override):
    auth_override("test-user-1")
    mock_cls, _ = _mapbox_mock()

    with (
        patch("src.api.routers.thumbnails.APISettings") as mock_settings,
        patch(
            "src.api.routers.thumbnails.get_geometry_data",
            new_callable=AsyncMock,
        ) as mock_get,
        patch("src.api.routers.thumbnails.httpx.AsyncClient", mock_cls),
    ):
        mock_settings.mapbox_api_token = "pk.test"
        mock_get.return_value = _MOCK_GEOMETRY_DATA

        response = await client.get(
            "/api/geometry/gadm/IND.2_1/thumbnail",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    assert "public" in response.headers["cache-control"]
    assert "max-age=86400" in response.headers["cache-control"]


@pytest.mark.asyncio
async def test_thumbnail_custom_dimensions_in_mapbox_url(
    client, auth_override
):
    auth_override("test-user-1")
    mock_cls, mock_client = _mapbox_mock()

    with (
        patch("src.api.routers.thumbnails.APISettings") as mock_settings,
        patch(
            "src.api.routers.thumbnails.get_geometry_data",
            new_callable=AsyncMock,
        ) as mock_get,
        patch("src.api.routers.thumbnails.httpx.AsyncClient", mock_cls),
    ):
        mock_settings.mapbox_api_token = "pk.test"
        mock_get.return_value = _MOCK_GEOMETRY_DATA

        response = await client.get(
            "/api/geometry/gadm/IND.2_1/thumbnail?width=640&height=480",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    called_url = mock_client.get.call_args[0][0]
    assert "640x480" in called_url


@pytest.mark.asyncio
async def test_thumbnail_uses_auto_camera_with_padding(client, auth_override):
    """Overlay must always use 'auto' camera with padding (no explicit center+zoom)."""
    auth_override("test-user-1")
    mock_cls, mock_client = _mapbox_mock()

    with (
        patch("src.api.routers.thumbnails.APISettings") as mock_settings,
        patch(
            "src.api.routers.thumbnails.get_geometry_data",
            new_callable=AsyncMock,
        ) as mock_get,
        patch("src.api.routers.thumbnails.httpx.AsyncClient", mock_cls),
    ):
        mock_settings.mapbox_api_token = "pk.test"
        mock_get.return_value = _MOCK_GEOMETRY_DATA

        await client.get(
            "/api/geometry/gadm/IND.2_1/thumbnail",
            headers={"Authorization": "Bearer test-token"},
        )

    called_url = mock_client.get.call_args[0][0]
    assert "/auto/" in called_url
    assert "padding=40" in called_url


@pytest.mark.asyncio
async def test_thumbnail_antimeridian_geometry_uses_auto_camera(
    client, auth_override
):
    """Russia-like antimeridian geometry must also use auto camera after stripping."""
    auth_override("test-user-1")
    russia_geom = shapely.geometry.mapping(_russia_like())
    mock_cls, mock_client = _mapbox_mock()

    with (
        patch("src.api.routers.thumbnails.APISettings") as mock_settings,
        patch(
            "src.api.routers.thumbnails.get_geometry_data",
            new_callable=AsyncMock,
        ) as mock_get,
        patch("src.api.routers.thumbnails.httpx.AsyncClient", mock_cls),
    ):
        mock_settings.mapbox_api_token = "pk.test"
        mock_get.return_value = {
            "name": "Russia",
            "source": "gadm",
            "geometry": russia_geom,
        }

        await client.get(
            "/api/geometry/gadm/RUS/thumbnail",
            headers={"Authorization": "Bearer test-token"},
        )

    called_url = mock_client.get.call_args[0][0]
    assert "/auto/" in called_url
    assert "padding=40" in called_url


@pytest.mark.asyncio
async def test_thumbnail_502_on_mapbox_http_error(client, auth_override):
    auth_override("test-user-1")

    mock_error_response = MagicMock()
    mock_error_response.status_code = 422
    mock_error_response.text = "Unprocessable Entity"

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(
        side_effect=httpx.HTTPStatusError(
            "error", request=MagicMock(), response=mock_error_response
        )
    )
    mock_cls = MagicMock()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("src.api.routers.thumbnails.APISettings") as mock_settings,
        patch(
            "src.api.routers.thumbnails.get_geometry_data",
            new_callable=AsyncMock,
        ) as mock_get,
        patch("src.api.routers.thumbnails.httpx.AsyncClient", mock_cls),
    ):
        mock_settings.mapbox_api_token = "pk.test"
        mock_get.return_value = _MOCK_GEOMETRY_DATA

        response = await client.get(
            "/api/geometry/gadm/IND.2_1/thumbnail",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 502
    assert "Thumbnail generation failed" in response.json()["detail"]


@pytest.mark.asyncio
async def test_thumbnail_502_on_mapbox_request_error(client, auth_override):
    auth_override("test-user-1")

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(
        side_effect=httpx.RequestError(
            "Connection refused", request=MagicMock()
        )
    )
    mock_cls = MagicMock()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("src.api.routers.thumbnails.APISettings") as mock_settings,
        patch(
            "src.api.routers.thumbnails.get_geometry_data",
            new_callable=AsyncMock,
        ) as mock_get,
        patch("src.api.routers.thumbnails.httpx.AsyncClient", mock_cls),
    ):
        mock_settings.mapbox_api_token = "pk.test"
        mock_get.return_value = _MOCK_GEOMETRY_DATA

        response = await client.get(
            "/api/geometry/gadm/IND.2_1/thumbnail",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 502
    assert "Thumbnail generation failed" in response.json()["detail"]


@pytest.mark.asyncio
async def test_thumbnail_mapbox_url_contains_access_token(
    client, auth_override
):
    auth_override("test-user-1")
    mock_cls, mock_client = _mapbox_mock()

    with (
        patch("src.api.routers.thumbnails.APISettings") as mock_settings,
        patch(
            "src.api.routers.thumbnails.get_geometry_data",
            new_callable=AsyncMock,
        ) as mock_get,
        patch("src.api.routers.thumbnails.httpx.AsyncClient", mock_cls),
    ):
        mock_settings.mapbox_api_token = "pk.my-secret-token"
        mock_get.return_value = _MOCK_GEOMETRY_DATA

        response = await client.get(
            "/api/geometry/gadm/IND.2_1/thumbnail",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    called_url = mock_client.get.call_args[0][0]
    assert "pk.my-secret-token" in called_url
    assert "access_token=" in called_url
