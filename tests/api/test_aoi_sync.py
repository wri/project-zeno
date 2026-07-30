"""Tests for the custom-area -> unified ``aois`` mirror.

``custom_areas`` stays the source of truth for the drawn GeoJSON list; every
CRUD call projects it into ``aois`` plus one ``owner`` row in ``user_aois``, in
the same transaction. These tests assert that projection, not the CRUD response
bodies (``test_custom_area.py`` covers those and must stay unchanged).
"""

import pytest
from sqlalchemy import text

from tests.conftest import async_session_maker

AUTH = {"Authorization": "Bearer abc123"}

_POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [
            [29.2263174, -1.641965],
            [29.2263174, -1.665582],
            [29.2301511, -1.665582],
            [29.2301511, -1.641965],
            [29.2263174, -1.641965],
        ]
    ],
}

# Two overlapping squares: ST_Union must dissolve them into a single-part
# MultiPolygon, so area_km2 is not double-counted.
_OVERLAPPING = [
    {
        "type": "Polygon",
        "coordinates": [
            [[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]]
        ],
    },
    {
        "type": "Polygon",
        "coordinates": [
            [[0.5, 0.0], [0.5, 1.0], [1.5, 1.0], [1.5, 0.0], [0.5, 0.0]]
        ],
    },
]

# A zero-area ring (duplicate points): ST_MakeValid yields no polygonal part,
# so the area must be skipped by the mirror without failing the CRUD call.
_DEGENERATE = {
    "type": "Polygon",
    "coordinates": [[[10.0, 10.0], [10.0, 10.0], [10.0, 10.0], [10.0, 10.0]]],
}


async def _create_area(client, name, geometries=None):
    res = await client.post(
        "/api/custom_areas",
        json={"name": name, "geometries": geometries or [_POLYGON]},
        headers=AUTH,
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def _fetch_aoi(area_id):
    """Return the mirrored (aois, user_aois) state for a custom area id."""
    async with async_session_maker() as session:
        row = (
            await session.execute(
                text(
                    "SELECT id, name, subtype, source, created_by, bbox, "
                    "area_km2, is_disputed, is_deprecated, "
                    "ST_GeometryType(geometry) AS gtype "
                    "FROM aois "
                    "WHERE source = 'custom' AND source_id = :src_id"
                ),
                {"src_id": area_id},
            )
        ).mappings()
        aoi = row.first()
        if aoi is None:
            return None, []
        links = (
            (
                await session.execute(
                    text(
                        "SELECT user_id, relationship, name FROM user_aois "
                        "WHERE aoi_id = :aoi_id"
                    ),
                    {"aoi_id": aoi["id"]},
                )
            )
            .mappings()
            .all()
        )
        return aoi, links


@pytest.mark.asyncio
async def test_create_mirrors_aoi_and_owner_link(auth_override, client):
    auth_override("test-user-wri")
    area_id = await _create_area(client, "Mirrored Area")

    aoi, links = await _fetch_aoi(area_id)
    assert aoi is not None, "create must project the area into aois"
    assert aoi["name"] == "Mirrored Area"
    assert aoi["subtype"] == "custom-area"
    assert aoi["created_by"] == "test-user-wri"
    assert aoi["is_disputed"] is False
    assert aoi["is_deprecated"] is False
    # Geometry is normalized to the typed MultiPolygon the column enforces.
    assert aoi["gtype"] == "ST_MultiPolygon"
    assert len(aoi["bbox"]) == 4
    assert aoi["area_km2"] > 0

    assert len(links) == 1
    assert links[0]["user_id"] == "test-user-wri"
    assert links[0]["relationship"] == "owner"
    # No per-user label yet; display falls back to aois.name.
    assert links[0]["name"] is None


@pytest.mark.asyncio
async def test_patch_updates_mirrored_name(auth_override, client):
    auth_override("test-user-wri")
    area_id = await _create_area(client, "Before")

    res = await client.patch(
        f"/api/custom_areas/{area_id}", json={"name": "After"}, headers=AUTH
    )
    assert res.status_code == 200, res.text

    aoi, links = await _fetch_aoi(area_id)
    assert aoi["name"] == "After"
    # The upsert must not create a second owner link on re-run.
    assert len(links) == 1


@pytest.mark.asyncio
async def test_delete_removes_mirror_and_cascades_link(auth_override, client):
    auth_override("test-user-wri")
    area_id = await _create_area(client, "Doomed")
    assert (await _fetch_aoi(area_id))[0] is not None

    res = await client.delete(f"/api/custom_areas/{area_id}", headers=AUTH)
    assert res.status_code == 204

    aoi, links = await _fetch_aoi(area_id)
    assert aoi is None
    assert links == []
    # The FK cascade must leave no orphaned relationship rows behind.
    async with async_session_maker() as session:
        remaining = await session.scalar(
            text("SELECT count(*) FROM user_aois")
        )
    assert remaining == 0


@pytest.mark.asyncio
async def test_overlapping_parts_are_dissolved(auth_override, client):
    auth_override("test-user-wri")
    area_id = await _create_area(client, "Overlapping", _OVERLAPPING)

    aoi, _ = await _fetch_aoi(area_id)
    # ST_Union merges the two overlapping squares into one part, so the shape
    # spans 0..1.5 in x and the overlap is counted once.
    assert aoi["gtype"] == "ST_MultiPolygon"
    assert aoi["bbox"][0] == pytest.approx(0.0)
    assert aoi["bbox"][2] == pytest.approx(1.5)
    async with async_session_maker() as session:
        parts = await session.scalar(
            text(
                "SELECT ST_NumGeometries(geometry) FROM aois "
                "WHERE source = 'custom' AND source_id = :src_id"
            ),
            {"src_id": area_id},
        )
    assert parts == 1


@pytest.mark.asyncio
async def test_degenerate_geometry_skipped_but_crud_succeeds(
    auth_override, client
):
    auth_override("test-user-wri")
    # The CRUD call must still succeed — custom_areas is the source of truth.
    area_id = await _create_area(client, "Degenerate", [_DEGENERATE])

    res = await client.get(f"/api/custom_areas/{area_id}", headers=AUTH)
    assert res.status_code == 200, res.text

    # ...but nothing searchable was projected, rather than an empty geometry.
    aoi, links = await _fetch_aoi(area_id)
    assert aoi is None
    assert links == []


@pytest.mark.asyncio
async def test_mirror_is_idempotent_across_repeated_patches(
    auth_override, client
):
    auth_override("test-user-wri")
    area_id = await _create_area(client, "Repeat")

    for name in ("One", "Two", "Three"):
        res = await client.patch(
            f"/api/custom_areas/{area_id}", json={"name": name}, headers=AUTH
        )
        assert res.status_code == 200, res.text

    async with async_session_maker() as session:
        aoi_count = await session.scalar(
            text(
                "SELECT count(*) FROM aois "
                "WHERE source = 'custom' AND source_id = :src_id"
            ),
            {"src_id": area_id},
        )
        link_count = await session.scalar(
            text("SELECT count(*) FROM user_aois")
        )
    assert aoi_count == 1
    assert link_count == 1


@pytest.mark.asyncio
async def test_mirror_is_scoped_to_the_created_area(
    auth_override, client, user_ds
):
    """A create must not re-project (or duplicate) other users' areas."""
    auth_override("test-user-wri")
    first = await _create_area(client, "First")

    # user_ds is pre-created so auth resolves it by id without an email clash.
    auth_override("test-user-ds")
    second = await _create_area(client, "Second")

    first_aoi, first_links = await _fetch_aoi(first)
    second_aoi, second_links = await _fetch_aoi(second)
    assert first_links[0]["user_id"] == "test-user-wri"
    assert second_links[0]["user_id"] == "test-user-ds"
    assert first_aoi["created_by"] == "test-user-wri"
    assert second_aoi["created_by"] == "test-user-ds"
