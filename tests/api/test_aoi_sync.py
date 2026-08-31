"""Tests for the mirror from a custom area into the unified ``aois`` table.

``custom_areas`` remains the source of truth for the drawn GeoJSON list. Every
CRUD call projects that list into ``aois``, and adds one ``owner`` row in
``user_aois``, in the same transaction. These tests assert the projection. They do
not assert the CRUD response bodies, which ``test_custom_area.py`` covers and which
must not change.
"""

import pytest
from sqlalchemy import text

from src.api.services.aoi_sync import (
    prune_orphan_custom_aois,
    upsert_custom_aoi,
)
from tests.conftest import async_session_maker, seed_reference_aoi

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

# Two squares that overlap. ST_Union must dissolve them into a MultiPolygon with
# one part, so area_km2 does not count the overlap twice.
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

# A ring with zero area, because every point repeats. ST_MakeValid gives no
# polygonal part, so the mirror must skip the area and the CRUD call must still
# succeed.
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
    """Return the mirrored ``aois`` and ``user_aois`` rows for a custom area."""
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
    # The mirror normalizes the geometry to the MultiPolygon type that the
    # column requires.
    assert aoi["gtype"] == "ST_MultiPolygon"
    assert len(aoi["bbox"]) == 4
    assert aoi["area_km2"] > 0

    assert len(links) == 1
    assert links[0]["user_id"] == "test-user-wri"
    assert links[0]["relationship"] == "owner"
    # The user has set no label, so the display reads aois.name.
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
    # A second run of the upsert must not create a second owner link.
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
    # The foreign key cascade must leave no relationship row without an AOI.
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
    # ST_Union joins the two squares into one part. The shape therefore spans
    # 0 to 1.5 in x, and the area counts the overlap once.
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
    # The CRUD call must still succeed, because custom_areas is the source of
    # truth.
    area_id = await _create_area(client, "Degenerate", [_DEGENERATE])

    res = await client.get(f"/api/custom_areas/{area_id}", headers=AUTH)
    assert res.status_code == 200, res.text

    # The mirror projects no searchable row. It does not store an empty geometry.
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
    """A create must not project the areas of another user a second time."""
    auth_override("test-user-wri")
    first = await _create_area(client, "First")

    # user_ds already exists, so auth resolves it by id and no email collides.
    auth_override("test-user-ds")
    second = await _create_area(client, "Second")

    first_aoi, first_links = await _fetch_aoi(first)
    second_aoi, second_links = await _fetch_aoi(second)
    assert first_links[0]["user_id"] == "test-user-wri"
    assert second_links[0]["user_id"] == "test-user-ds"
    assert first_aoi["created_by"] == "test-user-wri"
    assert second_aoi["created_by"] == "test-user-ds"


# ---------------------------------------------------------------------------
# properties: projected into aois.properties
# ---------------------------------------------------------------------------


async def _set_properties(area_id, properties):
    """Set ``custom_areas.properties`` directly and re-run the mirror.

    The create API does not accept properties; the upload endpoint sets them.
    This drives the same upsert SQL that endpoint runs.
    """
    async with async_session_maker() as session:
        await session.execute(
            text(
                "UPDATE custom_areas SET properties = CAST(:props AS jsonb) "
                "WHERE id::text = :id"
            ),
            {"props": properties, "id": area_id},
        )
        await upsert_custom_aoi(session, area_id=area_id)
        await session.commit()


async def _fetch_properties(area_id):
    async with async_session_maker() as session:
        return await session.scalar(
            text(
                "SELECT properties FROM aois "
                "WHERE source = 'custom' AND source_id = :src_id"
            ),
            {"src_id": area_id},
        )


@pytest.mark.asyncio
async def test_properties_mirrored_on_update(auth_override, client):
    """The DO UPDATE branch projects properties over the existing row."""
    auth_override("test-user-wri")
    area_id = await _create_area(client, "With Properties")
    assert await _fetch_properties(area_id) is None

    await _set_properties(area_id, '{"region": "Kivu", "code": 7}')

    assert await _fetch_properties(area_id) == {"region": "Kivu", "code": 7}


@pytest.mark.asyncio
async def test_null_properties_stays_null(auth_override, client):
    """A drawn area has no properties, and the mirror must keep the null."""
    auth_override("test-user-wri")
    area_id = await _create_area(client, "Drawn")

    res = await client.patch(
        f"/api/custom_areas/{area_id}",
        json={"name": "Still Drawn"},
        headers=AUTH,
    )
    assert res.status_code == 200, res.text

    assert await _fetch_properties(area_id) is None


# ---------------------------------------------------------------------------
# prune_orphan_custom_aois: repair a mirror that went out of step
# ---------------------------------------------------------------------------


async def _orphan_the_mirror(area_id):
    """Delete only the ``custom_areas`` row, so the mirror goes out of step.

    This is the state that a delete leaves behind when the write-through does
    not run, which is every delete before this feature shipped.
    """
    async with async_session_maker() as session:
        await session.execute(
            text("DELETE FROM custom_areas WHERE id::text = :id"),
            {"id": area_id},
        )
        await session.commit()


async def _prune():
    async with async_session_maker() as session:
        removed = await prune_orphan_custom_aois(session)
        await session.commit()
        return removed


async def _count(sql):
    async with async_session_maker() as session:
        return await session.scalar(text(sql))


@pytest.mark.asyncio
async def test_prune_removes_the_orphan_mirror(auth_override, client):
    auth_override("test-user-wri")
    kept = await _create_area(client, "Kept")
    orphan = await _create_area(client, "Orphan")
    await _orphan_the_mirror(orphan)

    assert await _prune() == 1

    assert await _fetch_aoi(orphan) == (None, [])
    kept_aoi, kept_links = await _fetch_aoi(kept)
    assert kept_aoi["name"] == "Kept"
    assert len(kept_links) == 1
    # The foreign key cascade took the orphan's owner link with the row.
    assert await _count("SELECT count(*) FROM user_aois") == 1


@pytest.mark.asyncio
async def test_prune_keeps_every_live_mirror(auth_override, client):
    """An inverted anti-join would delete every mirror. This test catches it."""
    auth_override("test-user-wri")
    await _create_area(client, "First")
    await _create_area(client, "Second")

    assert await _prune() == 0

    assert (
        await _count("SELECT count(*) FROM aois WHERE source = 'custom'") == 2
    )
    assert await _count("SELECT count(*) FROM user_aois") == 2


@pytest.mark.asyncio
async def test_prune_leaves_other_sources_alone(auth_override, client):
    """A missing source filter would delete every reference AOI."""
    auth_override("test-user-wri")
    await seed_reference_aoi("gadm", "IND.26_1", "Odisha", "state-province")
    orphan = await _create_area(client, "Orphan")
    await _orphan_the_mirror(orphan)

    assert await _prune() == 1

    assert await _count("SELECT count(*) FROM aois WHERE source = 'gadm'") == 1


@pytest.mark.asyncio
async def test_prune_does_not_commit(auth_override, client):
    """The caller owns the transaction, which is what makes --dry-run work."""
    auth_override("test-user-wri")
    orphan = await _create_area(client, "Orphan")
    await _orphan_the_mirror(orphan)

    async with async_session_maker() as session:
        assert await prune_orphan_custom_aois(session) == 1
        await session.rollback()

    aoi, _ = await _fetch_aoi(orphan)
    assert aoi is not None
