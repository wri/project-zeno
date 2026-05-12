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
    _crosses_antimeridian,
    _drop_empty_parts,
    _drop_interior_rings,
    _encode_overlay,
    _filter_small_parts,
    _fit_overlay,
    _geojson_feature,
    _simplify,
    _strip_antimeridian_spillover,
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
# _drop_empty_parts
# ---------------------------------------------------------------------------


def test_drop_empty_parts_non_multipolygon_unchanged():
    poly = _square(0, 0)
    result = _drop_empty_parts(poly)
    assert result is poly


def test_drop_empty_parts_removes_empty_geoms():
    """Empty sub-geometries (e.g. collapsed after simplification) are filtered out."""
    good = _square(0, 0, size=10)
    empty = shapely.geometry.Polygon()  # empty geometry
    # Use a mock so we can inject an empty geometry into geoms
    mp = MagicMock(spec=shapely.geometry.MultiPolygon)
    mp.geom_type = "MultiPolygon"
    mp.geoms = [good, empty]
    result = _drop_empty_parts(mp)
    assert result.geom_type == "Polygon"
    assert result.area == pytest.approx(good.area)


def test_drop_empty_parts_fallback_keeps_largest_when_all_empty():
    """If every part is empty, the one with the largest area is kept."""
    mp = MagicMock(spec=shapely.geometry.MultiPolygon)
    mp.geom_type = "MultiPolygon"
    e1, e2 = shapely.geometry.Polygon(), shapely.geometry.Polygon()
    mp.geoms = [e1, e2]
    result = _drop_empty_parts(mp)
    assert result is not None


def test_drop_empty_parts_single_survivor_is_polygon():
    good = _square(0, 0, size=10)
    empty = shapely.geometry.Polygon()
    mp = MagicMock(spec=shapely.geometry.MultiPolygon)
    mp.geom_type = "MultiPolygon"
    mp.geoms = [good, empty]
    result = _drop_empty_parts(mp)
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


def test_simplify_strips_interior_rings():
    """After simplification, interior rings must be absent from the output."""
    outer = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
    hole = [(2, 2), (4, 2), (4, 4), (2, 4), (2, 2)]
    poly_with_hole = shapely.geometry.Polygon(outer, [hole])
    geom = shapely.geometry.mapping(poly_with_hole)
    result = _simplify(geom, 0.001)
    result_shape = shapely.geometry.shape(result)
    assert len(list(result_shape.interiors)) == 0


# ---------------------------------------------------------------------------
# _simplify
# ---------------------------------------------------------------------------


def test_simplify_reduces_vertex_count():
    # A polygon with many vertices
    import math

    n = 100
    coords = [
        (math.cos(2 * math.pi * i / n), math.sin(2 * math.pi * i / n))
        for i in range(n)
    ]
    coords.append(coords[0])
    geom = {"type": "Polygon", "coordinates": [coords]}

    simplified = _simplify(geom, tolerance=0.1)
    original_shape = shapely.geometry.shape(geom)
    simplified_shape = shapely.geometry.shape(simplified)
    assert len(list(simplified_shape.exterior.coords)) < len(
        list(original_shape.exterior.coords)
    )


def test_simplify_returns_original_on_bad_geometry():
    bad = {"type": "NotAType", "coordinates": []}
    result = _simplify(bad, tolerance=0.01)
    assert result == bad


# ---------------------------------------------------------------------------
# _crosses_antimeridian
# ---------------------------------------------------------------------------


def _russia_like() -> shapely.geometry.MultiPolygon:
    """Two patches mimicking Russia: main landmass (19°–180°) + Chukotka (−170°–−155°).

    Chukotka is sized so its area fraction (~2.7%) exceeds the 0.5% filter threshold.
    """
    main = shapely.geometry.box(19, 41, 180, 82)
    chukotka = shapely.geometry.box(-170, 60, -155, 72)
    return shapely.geometry.MultiPolygon([main, chukotka])


def test_crosses_antimeridian_true_for_russia_like():
    assert _crosses_antimeridian(_russia_like()) is True


def test_crosses_antimeridian_false_for_normal_geometry():
    brazil = shapely.geometry.box(-73, -34, -28, 5)
    assert _crosses_antimeridian(brazil) is False


def test_crosses_antimeridian_false_for_new_zealand():
    nz = shapely.geometry.box(166, -48, 178, -34)
    assert _crosses_antimeridian(nz) is False


# ---------------------------------------------------------------------------
# _strip_antimeridian_spillover
# ---------------------------------------------------------------------------


def test_strip_antimeridian_spillover_removes_minority_side():
    """Chukotka (negative lons, small area) must be removed; main Russia kept."""
    shape = _russia_like()
    result = _strip_antimeridian_spillover(shape)
    coords = shapely.get_coordinates(result)
    lons = coords[:, 0]
    assert (
        lons >= 0
    ).all(), f"Expected only non-negative lons, got min={lons.min()}"


def test_strip_antimeridian_spillover_non_crossing_unchanged():
    shape = shapely.geometry.box(0, 0, 10, 10)
    result = _strip_antimeridian_spillover(shape)
    assert result is shape


def test_strip_antimeridian_spillover_non_multipolygon_unchanged():
    """A single Polygon crossing the antimeridian is returned as-is."""
    # A single polygon that spans from -100 to +100 (crosses detection threshold)
    shape = shapely.geometry.box(-100, 0, 100, 10)
    result = _strip_antimeridian_spillover(shape)
    assert result is shape  # non-MultiPolygon passed through


def test_strip_antimeridian_spillover_result_does_not_cross():
    """After stripping, the shape must no longer cross the antimeridian."""
    shape = _russia_like()
    result = _strip_antimeridian_spillover(shape)
    assert not _crosses_antimeridian(result)


def test_strip_antimeridian_spillover_usa_like():
    """For USA-like geometry (dominant side is negative lons), keep the negative side."""
    contiguous = shapely.geometry.box(
        -124, 24, -66, 49
    )  # contiguous USA (large)
    aleutians = shapely.geometry.box(
        172, 51, 175, 53
    )  # Attu Island, positive lons (tiny)
    usa = shapely.geometry.MultiPolygon([contiguous, aleutians])
    result = _strip_antimeridian_spillover(usa)
    coords = shapely.get_coordinates(result)
    lons = coords[:, 0]
    assert (
        lons <= 0
    ).all(), f"Expected only non-positive lons, got max={lons.max()}"


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


def test_fit_overlay_russia_like_within_budget():
    """Russia-like antimeridian geometry must fit after stripping."""
    mp = shapely.geometry.mapping(_russia_like())
    encoded = _fit_overlay(mp)
    assert len(encoded) <= _MAX_OVERLAY_CHARS
    # Decoded overlay must have no negative lons (Chukotka stripped)
    decoded = json.loads(urllib.parse.unquote(encoded))
    geom = decoded.get("geometry", decoded)
    coords_raw = geom.get("coordinates", [])

    def all_lons(obj):
        if isinstance(obj, list):
            if len(obj) >= 2 and isinstance(obj[0], (int, float)):
                return [obj[0]]
            result = []
            for item in obj:
                result.extend(all_lons(item))
            return result
        return []

    lons = all_lons(coords_raw)
    assert lons, "No coordinates found in overlay"
    assert all(
        lon >= 0 for lon in lons
    ), f"Found negative lon in overlay: {min(lons)}"


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
