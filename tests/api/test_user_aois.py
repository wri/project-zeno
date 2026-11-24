"""Tests for the user's area library: the ``user_aois`` rows behind "My areas"."""

import pytest

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


async def list_library(client):
    res = await client.get("/api/user_aois", headers=AUTH)
    assert res.status_code == 200, res.text
    return res.json()


@pytest.mark.asyncio
async def test_my_areas_lists_the_users_custom_areas_without_geometry(
    auth_override, client
):
    auth_override("test-user-wri")
    area_id = await create_custom_area(client, "Farm plot")

    (entry,) = await list_library(client)

    assert entry["relationship"] == "owner"
    assert entry["name"] == "Farm plot"
    assert entry["source"] == "custom"
    assert entry["src_id"] == area_id
    assert entry["subtype"] == "custom-area"
    assert entry["bbox"] == pytest.approx([29.0, -2.0, 30.0, -1.0])
    assert "geometry" not in entry and "geometries" not in entry


@pytest.mark.asyncio
async def test_my_areas_shows_only_the_callers_rows(
    auth_override, client, user_ds
):
    auth_override("test-user-wri")
    await create_custom_area(client, "Mine")
    auth_override("test-user-ds")
    await create_custom_area(client, "Theirs")

    assert [e["name"] for e in await list_library(client)] == ["Theirs"]


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

    assert [e["name"] for e in await list_library(client)] == ["New name"]
