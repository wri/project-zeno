"""Tests for ``POST /api/custom_areas/upload`` with a CSV file.

Each uploaded feature becomes a regular custom area, so these tests assert the
whole chain: the ``custom_areas`` rows, the shared ``upload_batch_id``, the
mirror into ``aois``, search through ``GET /api/aois``, and owner scoping.
"""

import csv
import io

import pytest
from sqlalchemy import text

from src.api.services.area_upload import MAX_FEATURES, MAX_UPLOAD_BYTES
from tests.conftest import async_session_maker

AUTH = {"Authorization": "Bearer abc123"}

_SQUARE = "POLYGON ((30 10, 30 11, 31 11, 31 10, 30 10))"
_MULTI = "MULTIPOLYGON (((5 5, 5 6, 6 6, 6 5, 5 5)))"


def _csv(rows, header=("name", "geom")):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    return buf.getvalue().encode()


async def _upload(client, content, filename="areas.csv"):
    return await client.post(
        "/api/custom_areas/upload",
        files={"file": (filename, content, "text/csv")},
        headers=AUTH,
    )


async def _counts():
    async with async_session_maker() as session:
        areas = await session.scalar(text("SELECT count(*) FROM custom_areas"))
        aois = await session.scalar(
            text("SELECT count(*) FROM aois WHERE source = 'custom'")
        )
    return areas, aois


@pytest.mark.asyncio
async def test_upload_creates_areas_and_mirrors(
    auth_override, client, user_ds
):
    auth_override("test-user-wri")
    content = _csv(
        [
            ("Upland North", _SQUARE, "Kivu", "7"),
            ("Upland South", _MULTI, "Ituri", ""),
        ],
        header=("name", "geom", "region", "code"),
    )

    res = await _upload(client, content)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["upload_batch_id"]
    assert [a["name"] for a in body["areas"]] == [
        "Upland North",
        "Upland South",
    ]

    # The rows are regular custom areas, newest first in the list.
    res = await client.get("/api/custom_areas", headers=AUTH)
    listed = res.json()
    assert len(listed) == 2
    by_name = {a["name"]: a for a in listed}
    assert (
        by_name["Upland North"]["upload_batch_id"] == (body["upload_batch_id"])
    )
    assert (
        by_name["Upland South"]["upload_batch_id"] == (body["upload_batch_id"])
    )
    assert by_name["Upland North"]["properties"] == {
        "region": "Kivu",
        "code": "7",
    }
    assert by_name["Upland North"]["geometries"][0]["type"] == "Polygon"
    assert by_name["Upland South"]["geometries"][0]["type"] == "MultiPolygon"

    # The mirror projects each row, with its properties.
    async with async_session_maker() as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT name, properties, "
                        "ST_GeometryType(geometry) AS gtype "
                        "FROM aois WHERE source = 'custom' ORDER BY name"
                    )
                )
            )
            .mappings()
            .all()
        )
    assert [r["name"] for r in rows] == ["Upland North", "Upland South"]
    assert rows[0]["properties"] == {"region": "Kivu", "code": "7"}
    assert all(r["gtype"] == "ST_MultiPolygon" for r in rows)

    # The owner finds the areas through search; another user does not.
    res = await client.get("/api/aois?name=Upland&source=custom", headers=AUTH)
    assert {r["name"] for r in res.json()} == {
        "Upland North",
        "Upland South",
    }

    auth_override("test-user-ds")
    res = await client.get("/api/aois?name=Upland&source=custom", headers=AUTH)
    assert res.json() == []
    res = await client.get("/api/custom_areas", headers=AUTH)
    assert res.json() == []


@pytest.mark.asyncio
async def test_drawn_area_has_no_batch_id(auth_override, client):
    auth_override("test-user-wri")
    res = await client.post(
        "/api/custom_areas",
        json={
            "name": "Drawn",
            "geometries": [
                {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]],
                }
            ],
        },
        headers=AUTH,
    )
    assert res.status_code == 200, res.text

    res = await client.get("/api/custom_areas", headers=AUTH)
    assert res.json()[0]["upload_batch_id"] is None
    assert res.json()[0]["properties"] is None


@pytest.mark.asyncio
async def test_upload_missing_geom_column(auth_override, client):
    auth_override("test-user-wri")
    res = await _upload(client, _csv([("Area", "x")], header=("name", "wkt")))
    assert res.status_code == 422
    assert res.json()["detail"]["errors"] == ["missing required column: geom"]


@pytest.mark.asyncio
async def test_upload_uppercase_headers_accepted(auth_override, client):
    auth_override("test-user-wri")
    res = await _upload(
        client, _csv([("Area", _SQUARE)], header=("NAME", "GEOM"))
    )
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_upload_bad_rows_report_each_and_create_nothing(
    auth_override, client
):
    auth_override("test-user-wri")
    content = _csv(
        [
            ("Bad WKT", "POLYGON((oops"),
            ("A Point", "POINT (30 10)"),
            ("", _SQUARE),
            ("Good", _SQUARE),
        ]
    )

    res = await _upload(client, content)
    assert res.status_code == 422
    errors = res.json()["detail"]["errors"]
    assert len(errors) == 3
    assert errors[0].startswith("row 1: invalid WKT")
    assert errors[1] == (
        "row 2: geometry must be a Polygon or MultiPolygon, got Point"
    )
    assert errors[2] == "row 3: name is empty"

    # All-or-nothing: the good row must not survive the bad ones.
    assert await _counts() == (0, 0)


@pytest.mark.asyncio
async def test_upload_projected_coordinates_rejected(auth_override, client):
    auth_override("test-user-wri")
    projected = (
        "POLYGON ((500000 4649776, 500000 4650776, "
        "501000 4650776, 500000 4649776))"
    )
    res = await _upload(client, _csv([("Projected", projected)]))
    assert res.status_code == 422
    assert "WGS84" in res.json()["detail"]["errors"][0]


@pytest.mark.asyncio
async def test_upload_empty_and_header_only_files(auth_override, client):
    auth_override("test-user-wri")
    res = await _upload(client, b"")
    assert res.status_code == 422
    assert res.json()["detail"]["errors"] == ["file is empty"]

    res = await _upload(client, _csv([]))
    assert res.status_code == 422
    assert res.json()["detail"]["errors"] == ["file has no data rows"]


@pytest.mark.asyncio
async def test_upload_too_many_rows(auth_override, client):
    auth_override("test-user-wri")
    rows = [(f"Area {i}", _SQUARE) for i in range(MAX_FEATURES + 1)]
    res = await _upload(client, _csv(rows))
    assert res.status_code == 422
    assert "limit is" in res.json()["detail"]["errors"][0]
    assert await _counts() == (0, 0)


@pytest.mark.asyncio
async def test_upload_rejects_unsupported_extension(auth_override, client):
    auth_override("test-user-wri")
    res = await _upload(client, _csv([("Area", _SQUARE)]), "areas.txt")
    assert res.status_code == 415


@pytest.mark.asyncio
async def test_upload_rejects_oversize_file(auth_override, client):
    auth_override("test-user-wri")
    res = await _upload(client, b"a" * (MAX_UPLOAD_BYTES + 1))
    assert res.status_code == 413
    assert await _counts() == (0, 0)


# ---------------------------------------------------------------------------
# Zipped shapefile uploads
# ---------------------------------------------------------------------------


def _shapefile_zip(gdf, drop_prj=False):
    """Write *gdf* to a shapefile in a temp dir and zip every sidecar file."""
    import os
    import tempfile
    import zipfile

    buf = io.BytesIO()
    with tempfile.TemporaryDirectory() as tmpdir:
        gdf.to_file(os.path.join(tmpdir, "areas.shp"))
        if drop_prj:
            os.remove(os.path.join(tmpdir, "areas.prj"))
        with zipfile.ZipFile(buf, "w") as archive:
            for entry in sorted(os.listdir(tmpdir)):
                archive.write(os.path.join(tmpdir, entry), entry)
    return buf.getvalue()


def _square(minx, miny):
    from shapely.geometry import Polygon

    return Polygon(
        [
            (minx, miny),
            (minx, miny + 1),
            (minx + 1, miny + 1),
            (minx + 1, miny),
        ]
    )


async def _upload_zip(client, content, filename="areas.zip"):
    return await client.post(
        "/api/custom_areas/upload",
        files={"file": (filename, content, "application/zip")},
        headers=AUTH,
    )


@pytest.mark.asyncio
async def test_shapefile_upload_creates_areas_and_mirrors(
    auth_override, client
):
    import geopandas as gpd

    auth_override("test-user-wri")
    gdf = gpd.GeoDataFrame(
        {
            "name": ["Shape North", "Shape South"],
            "region": ["Kivu", "Ituri"],
            "geometry": [_square(30, 10), _square(5, 5)],
        },
        crs="EPSG:4326",
    )

    res = await _upload_zip(client, _shapefile_zip(gdf))
    assert res.status_code == 200, res.text
    body = res.json()
    assert [a["name"] for a in body["areas"]] == [
        "Shape North",
        "Shape South",
    ]

    res = await client.get("/api/custom_areas", headers=AUTH)
    by_name = {a["name"]: a for a in res.json()}
    assert len(by_name) == 2
    assert by_name["Shape North"]["properties"] == {"region": "Kivu"}
    assert (
        by_name["Shape North"]["upload_batch_id"] == (body["upload_batch_id"])
    )

    assert await _counts() == (2, 2)


@pytest.mark.asyncio
async def test_shapefile_uppercase_name_field(auth_override, client):
    import geopandas as gpd

    auth_override("test-user-wri")
    gdf = gpd.GeoDataFrame(
        {"NAME": ["Upper"], "geometry": [_square(30, 10)]},
        crs="EPSG:4326",
    )

    res = await _upload_zip(client, _shapefile_zip(gdf))
    assert res.status_code == 200, res.text
    assert res.json()["areas"][0]["name"] == "Upper"


@pytest.mark.asyncio
async def test_shapefile_missing_prj(auth_override, client):
    import geopandas as gpd

    auth_override("test-user-wri")
    gdf = gpd.GeoDataFrame(
        {"name": ["No CRS"], "geometry": [_square(30, 10)]},
        crs="EPSG:4326",
    )

    res = await _upload_zip(client, _shapefile_zip(gdf, drop_prj=True))
    assert res.status_code == 422
    assert ".prj" in res.json()["detail"]["errors"][0]
    assert await _counts() == (0, 0)


@pytest.mark.asyncio
async def test_shapefile_projected_crs_is_reprojected(auth_override, client):
    import geopandas as gpd

    auth_override("test-user-wri")
    gdf = gpd.GeoDataFrame(
        {"name": ["Projected"], "geometry": [_square(30, 10)]},
        crs="EPSG:4326",
    ).to_crs("EPSG:3857")

    res = await _upload_zip(client, _shapefile_zip(gdf))
    assert res.status_code == 200, res.text

    # The mirror must hold lon/lat again, not Web Mercator meters.
    async with async_session_maker() as session:
        bbox = await session.scalar(
            text("SELECT bbox FROM aois WHERE source = 'custom'")
        )
    assert bbox[0] == pytest.approx(30, abs=1e-6)
    assert bbox[1] == pytest.approx(10, abs=1e-6)


@pytest.mark.asyncio
async def test_shapefile_point_geometry_rejected(auth_override, client):
    import geopandas as gpd
    from shapely.geometry import Point

    auth_override("test-user-wri")
    gdf = gpd.GeoDataFrame(
        {"name": ["A Point"], "geometry": [Point(30, 10)]},
        crs="EPSG:4326",
    )

    res = await _upload_zip(client, _shapefile_zip(gdf))
    assert res.status_code == 422
    errors = res.json()["detail"]["errors"]
    assert errors[0] == (
        "feature 1: geometry must be a Polygon or MultiPolygon, got Point"
    )
    assert await _counts() == (0, 0)


@pytest.mark.asyncio
async def test_shapefile_attributes_sanitized_to_json(auth_override, client):
    import datetime

    import geopandas as gpd

    auth_override("test-user-wri")
    gdf = gpd.GeoDataFrame(
        {
            "name": ["First", "Second"],
            "code": [7.0, None],
            "when": [datetime.date(2026, 1, 15), datetime.date(2026, 2, 2)],
            "geometry": [_square(30, 10), _square(5, 5)],
        },
        crs="EPSG:4326",
    )

    res = await _upload_zip(client, _shapefile_zip(gdf))
    assert res.status_code == 200, res.text

    res = await client.get("/api/custom_areas", headers=AUTH)
    by_name = {a["name"]: a for a in res.json()}
    assert by_name["First"]["properties"]["code"] == 7.0
    assert by_name["Second"]["properties"]["code"] is None
    assert by_name["First"]["properties"]["when"].startswith("2026-01-15")


@pytest.mark.asyncio
async def test_shapefile_empty_name_rejected(auth_override, client):
    import geopandas as gpd

    auth_override("test-user-wri")
    gdf = gpd.GeoDataFrame(
        {"name": [None], "geometry": [_square(30, 10)]},
        crs="EPSG:4326",
    )

    res = await _upload_zip(client, _shapefile_zip(gdf))
    assert res.status_code == 422
    assert res.json()["detail"]["errors"] == ["feature 1: name is empty"]


@pytest.mark.asyncio
async def test_zip_without_a_shapefile(auth_override, client):
    import zipfile

    auth_override("test-user-wri")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("readme.txt", "not a shapefile")

    res = await _upload_zip(client, buf.getvalue())
    assert res.status_code == 422
    assert "could not read" in res.json()["detail"]["errors"][0]


def test_shapefile_feature_cap():
    import geopandas as gpd

    from src.api.services.area_upload import (
        UploadValidationError,
        parse_shapefile_zip,
    )

    count = MAX_FEATURES + 1
    gdf = gpd.GeoDataFrame(
        {
            "name": [f"Area {i}" for i in range(count)],
            "geometry": [_square(i % 100, i % 50) for i in range(count)],
        },
        crs="EPSG:4326",
    )

    with pytest.raises(UploadValidationError) as excinfo:
        parse_shapefile_zip(_shapefile_zip(gdf))
    assert "limit is" in excinfo.value.errors[0]
