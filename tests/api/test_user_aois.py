"""Tests for the user's areas: the ``user_aois`` rows behind "My areas"."""

import pytest
from sqlalchemy import text

from tests.conftest import async_session_maker, seed_reference_aoi

AUTH = {"Authorization": "Bearer abc123"}

SQUARE = {
    "type": "Polygon",
    "coordinates": [
        [[29.0, -1.0], [29.0, -2.0], [30.0, -2.0], [30.0, -1.0], [29.0, -1.0]]
    ],
}


async def create_custom_area(client, name):
    res = await client.post(
        "/api/custom_areas",
        json={"name": name, "geometries": [SQUARE]},
        headers=AUTH,
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def save_area(client, source, src_id, name=None):
    return await client.post(
        "/api/user_aois",
        json={"source": source, "src_id": src_id, "name": name},
        headers=AUTH,
    )


async def count_rows(table):
    async with async_session_maker() as session:
        return await session.scalar(text(f"SELECT count(*) FROM {table}"))


async def list_user_aois(client):
    res = await client.get("/api/user_aois", headers=AUTH)
    assert res.status_code == 200, res.text
    return res.json()


@pytest.mark.asyncio
async def test_my_areas_lists_the_users_custom_areas_without_geometry(
    auth_override, client
):
    auth_override("test-user-wri")
    area_id = await create_custom_area(client, "Farm plot")

    (user_aoi,) = await list_user_aois(client)

    assert user_aoi["relationship"] == "owner"
    assert user_aoi["name"] == "Farm plot"
    assert user_aoi["source"] == "custom"
    assert user_aoi["src_id"] == area_id
    assert user_aoi["subtype"] == "custom-area"
    assert user_aoi["bbox"] == pytest.approx([29.0, -2.0, 30.0, -1.0])
    assert "geometry" not in user_aoi and "geometries" not in user_aoi


@pytest.mark.asyncio
async def test_my_areas_shows_only_the_callers_rows(
    auth_override, client, user_ds
):
    auth_override("test-user-wri")
    await create_custom_area(client, "Mine")
    auth_override("test-user-ds")
    await create_custom_area(client, "Theirs")

    assert [e["name"] for e in await list_user_aois(client)] == ["Theirs"]


@pytest.mark.asyncio
async def test_my_areas_lists_newest_first_in_pages(auth_override, client):
    auth_override("test-user-wri")
    for name in ("First", "Second", "Third"):
        await create_custom_area(client, name)

    res = await client.get("/api/user_aois?limit=2", headers=AUTH)
    assert [e["name"] for e in res.json()] == ["Third", "Second"]
    assert res.headers["X-Next-Offset"] == "2"

    res = await client.get("/api/user_aois?limit=2&offset=2", headers=AUTH)
    assert [e["name"] for e in res.json()] == ["First"]
    assert "X-Next-Offset" not in res.headers


@pytest.mark.asyncio
async def test_renaming_a_custom_area_renames_it_in_my_areas(
    auth_override, client
):
    auth_override("test-user-wri")
    area_id = await create_custom_area(client, "Old name")

    res = await client.patch(
        f"/api/custom_areas/{area_id}", json={"name": "New name"}, headers=AUTH
    )
    assert res.status_code == 200, res.text

    assert [e["name"] for e in await list_user_aois(client)] == ["New name"]


@pytest.mark.asyncio
async def test_saving_a_source_area_copies_no_geometry(
    auth_override, client, custom_aoi_analytics
):
    auth_override("test-user-wri")
    await seed_reference_aoi("gadm", "BRA", "Brazil", "country")

    res = await save_area(client, "gadm", "BRA")

    assert res.status_code == 201, res.text
    assert await count_rows("custom_areas") == 0
    assert await count_rows("aois") == 1
    assert custom_aoi_analytics.saved == []


@pytest.mark.asyncio
async def test_saved_area_lists_with_its_source_identity(
    auth_override, client
):
    auth_override("test-user-wri")
    await seed_reference_aoi("gadm", "BRA", "Brazil", "country")
    await seed_reference_aoi(
        "kba", "12345", "Mount Kenya", "key-biodiversity-area"
    )
    await save_area(client, "gadm", "BRA", name="Project country")
    await save_area(client, "kba", 12345)

    kba, gadm = await list_user_aois(client)

    assert (gadm["relationship"], gadm["name"]) == ("saved", "Project country")
    assert (gadm["source"], gadm["src_id"], gadm["subtype"]) == (
        "gadm",
        "BRA",
        "country",
    )
    assert (kba["name"], kba["src_id"]) == ("Mount Kenya", 12345)


@pytest.mark.asyncio
async def test_saving_the_same_area_twice_conflicts(auth_override, client):
    auth_override("test-user-wri")
    await seed_reference_aoi("gadm", "BRA", "Brazil", "country")
    await save_area(client, "gadm", "BRA")

    res = await save_area(client, "gadm", "BRA")

    assert res.status_code == 409, res.text
    assert len(await list_user_aois(client)) == 1


@pytest.mark.asyncio
async def test_unknown_source_area_is_not_found(auth_override, client):
    auth_override("test-user-wri")

    res = await save_area(client, "gadm", "XXX")

    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_a_custom_area_cannot_be_saved_as_a_reference(
    auth_override, client
):
    auth_override("test-user-wri")
    area_id = await create_custom_area(client, "Farm plot")

    res = await save_area(client, "custom", area_id)

    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_renaming_a_saved_area_changes_only_the_users_label(
    auth_override, client
):
    auth_override("test-user-wri")
    await seed_reference_aoi("gadm", "BRA", "Brazil", "country")
    user_aoi_id = (await save_area(client, "gadm", "BRA")).json()["id"]

    res = await client.patch(
        f"/api/user_aois/{user_aoi_id}", json={"name": "Project"}, headers=AUTH
    )

    assert res.status_code == 200, res.text
    assert res.json()["name"] == "Project"
    async with async_session_maker() as session:
        name = await session.scalar(
            text("SELECT name FROM aois WHERE source_id = 'BRA'")
        )
    assert name == "Brazil"


@pytest.mark.asyncio
async def test_deleting_a_saved_area_removes_only_the_link(
    auth_override, client
):
    auth_override("test-user-wri")
    await seed_reference_aoi("gadm", "BRA", "Brazil", "country")
    user_aoi_id = (await save_area(client, "gadm", "BRA")).json()["id"]

    res = await client.delete(f"/api/user_aois/{user_aoi_id}", headers=AUTH)

    assert res.status_code == 204, res.text
    assert await list_user_aois(client) == []
    assert await count_rows("aois") == 1


@pytest.mark.asyncio
async def test_renaming_and_deleting_an_owned_user_aoi_acts_on_the_custom_area(
    auth_override, client, custom_aoi_analytics
):
    auth_override("test-user-wri")
    area_id = await create_custom_area(client, "Old name")
    (user_aoi,) = await list_user_aois(client)

    res = await client.patch(
        f"/api/user_aois/{user_aoi['id']}",
        json={"name": "New name"},
        headers=AUTH,
    )
    assert res.status_code == 200, res.text
    area = await client.get(f"/api/custom_areas/{area_id}", headers=AUTH)
    assert area.json()["name"] == "New name"

    res = await client.delete(f"/api/user_aois/{user_aoi['id']}", headers=AUTH)
    assert res.status_code == 204, res.text
    area = await client.get(f"/api/custom_areas/{area_id}", headers=AUTH)
    assert area.status_code == 404
    assert custom_aoi_analytics.deleted == [area_id]


@pytest.mark.asyncio
async def test_users_cannot_change_another_users_area(
    auth_override, client, user_ds
):
    auth_override("test-user-wri")
    await seed_reference_aoi("gadm", "BRA", "Brazil", "country")
    user_aoi_id = (await save_area(client, "gadm", "BRA")).json()["id"]

    auth_override("test-user-ds")
    renamed = await client.patch(
        f"/api/user_aois/{user_aoi_id}", json={"name": "Mine"}, headers=AUTH
    )
    deleted = await client.delete(
        f"/api/user_aois/{user_aoi_id}", headers=AUTH
    )

    assert (renamed.status_code, deleted.status_code) == (404, 404)
