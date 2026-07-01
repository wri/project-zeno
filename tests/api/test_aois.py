"""Tests for the unified AOI search endpoint (GET /api/aois).

The test database only contains the ORM tables (custom_areas), so the reference
sources (gadm/kba/wdpa/landmark) are skipped by search_aois and these tests
exercise the custom-area path, source filtering, pagination and validation.
"""

import pytest

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

AUTH = {"Authorization": "Bearer abc123"}


async def _create_area(client, name):
    res = await client.post(
        "/api/custom_areas",
        json={"name": name, "geometries": [_POLYGON]},
        headers=AUTH,
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


@pytest.mark.asyncio
async def test_search_by_name(auth_override, client):
    auth_override("test-user-wri")
    await _create_area(client, "Amazon")
    await _create_area(client, "Amazonia")
    await _create_area(client, "Sahara")

    res = await client.get("/api/aois?name=amazon", headers=AUTH)
    assert res.status_code == 200, res.text
    results = res.json()
    names = [r["name"] for r in results]
    assert "Amazon" in names
    assert "Amazonia" in names
    assert "Sahara" not in names
    # The exact-match custom area is returned with the expected shape.
    amazon = next(r for r in results if r["name"] == "Amazon")
    assert amazon["source"] == "custom"
    assert amazon["subtype"] == "custom-area"
    assert len(amazon["bbox"]) == 4


@pytest.mark.asyncio
async def test_browse_custom_without_name(auth_override, client):
    auth_override("test-user-wri")
    await _create_area(client, "Area B")
    await _create_area(client, "Area A")
    await _create_area(client, "Area C")

    res = await client.get("/api/aois?source=custom", headers=AUTH)
    assert res.status_code == 200, res.text
    names = [r["name"] for r in res.json()]
    # Browse mode is ordered alphabetically by name.
    assert names == ["Area A", "Area B", "Area C"]


@pytest.mark.asyncio
async def test_results_scoped_to_owner(auth_override, client, user_ds):
    auth_override("test-user-wri")
    await _create_area(client, "Owned Area")

    # A different user must not see another user's custom areas.
    # (user_ds is pre-created so auth resolves it by id without an email clash.)
    auth_override("test-user-ds")
    res = await client.get("/api/aois?source=custom", headers=AUTH)
    assert res.status_code == 200, res.text
    assert res.json() == []


@pytest.mark.asyncio
async def test_pagination(auth_override, client):
    auth_override("test-user-wri")
    for name in ["Area A", "Area B", "Area C"]:
        await _create_area(client, name)

    first = await client.get("/api/aois?source=custom&limit=2", headers=AUTH)
    assert first.status_code == 200, first.text
    assert [r["name"] for r in first.json()] == ["Area A", "Area B"]
    assert first.headers["x-next-offset"] == "2"

    offset = first.headers["x-next-offset"]
    second = await client.get(
        f"/api/aois?source=custom&limit=2&offset={offset}", headers=AUTH
    )
    assert second.status_code == 200, second.text
    assert [r["name"] for r in second.json()] == ["Area C"]
    assert "x-next-offset" not in second.headers


@pytest.mark.asyncio
async def test_invalid_source_returns_422(auth_override, client):
    auth_override("test-user-wri")
    res = await client.get("/api/aois?source=bogus", headers=AUTH)
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_protectedareas_alias_accepted(auth_override, client):
    auth_override("test-user-wri")
    # The "protectedareas" alias resolves to the wdpa source.
    res = await client.get("/api/aois?source=protectedareas", headers=AUTH)
    assert res.status_code == 200, res.text
    # Environment-independent: any rows returned must be wdpa.
    assert all(r["source"] == "wdpa" for r in res.json())


@pytest.mark.asyncio
async def test_requires_auth(client):
    res = await client.get("/api/aois?source=custom")
    assert res.status_code == 401
