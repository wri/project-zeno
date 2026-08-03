"""Tests for the unified AOI search endpoint (GET /api/aois).

Search reads the unified ``aois`` table, which is part of the ORM metadata, so
reference sources can be seeded directly here -- custom areas still arrive
through ``POST /api/custom_areas`` and its mirror, exercising the write path
that search depends on.
"""

import pytest
from sqlalchemy import text

from tests.conftest import async_session_maker
from tests.conftest import seed_reference_aoi as _seed_reference_aoi

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


@pytest.mark.asyncio
async def test_disputed_rows_excluded_but_still_resolvable(
    auth_override, client
):
    """Disputed rows are absent from search yet addressable by (source, id)."""
    auth_override("test-user-wri")
    await _seed_reference_aoi("gadm", "BRA", "Brazil", "country")
    await _seed_reference_aoi(
        "gadm", "Z01", "Brazilia Disputed", "country", is_disputed=True
    )

    res = await client.get("/api/aois?name=brazil&source=gadm", headers=AUTH)
    assert res.status_code == 200, res.text
    src_ids = [r["src_id"] for r in res.json()]
    assert "BRA" in src_ids
    assert "Z01" not in src_ids

    # Browse mode must exclude it too, not just the similarity path.
    res = await client.get("/api/aois?source=gadm", headers=AUTH)
    assert [r["src_id"] for r in res.json()] == ["BRA"]

    # ...but the row is still there for geometry fetches / analytics linkage.
    async with async_session_maker() as session:
        found = await session.scalar(
            text(
                "SELECT name FROM aois "
                "WHERE source = 'gadm' AND source_id = 'Z01'"
            )
        )
    assert found == "Brazilia Disputed"


@pytest.mark.asyncio
async def test_search_ranks_across_sources(auth_override, client):
    """One ranked list spanning reference sources and the caller's own areas."""
    auth_override("test-user-wri")
    await _seed_reference_aoi(
        "wdpa", "555", "Amazonia Protected", "protected-area"
    )
    await _seed_reference_aoi(
        "kba", "42", "Amazon Key Area", "key-biodiversity-area"
    )
    await _create_area(client, "Amazon")

    res = await client.get("/api/aois?name=amazon", headers=AUTH)
    assert res.status_code == 200, res.text
    results = res.json()
    assert {r["source"] for r in results} == {"wdpa", "kba", "custom"}
    # Exact match outranks the longer partial matches.
    assert results[0]["name"] == "Amazon"
    assert results[0]["source"] == "custom"


@pytest.mark.asyncio
async def test_browse_orders_by_name_then_source(auth_override, client):
    """Browse tie-break is (name, source, src_id) across all sources."""
    auth_override("test-user-wri")
    await _seed_reference_aoi("wdpa", "1", "Shared Name", "protected-area")
    await _seed_reference_aoi(
        "kba", "2", "Shared Name", "key-biodiversity-area"
    )
    await _seed_reference_aoi("gadm", "AAA", "Aardvark Land", "country")

    res = await client.get("/api/aois", headers=AUTH)
    assert res.status_code == 200, res.text
    rows = [(r["name"], r["source"]) for r in res.json()]
    assert rows == [
        ("Aardvark Land", "gadm"),
        ("Shared Name", "kba"),
        ("Shared Name", "wdpa"),
    ]


@pytest.mark.asyncio
async def test_reference_sources_are_not_owner_scoped(
    auth_override, client, user_ds
):
    """Only custom areas are owner-scoped; reference rows are shared."""
    auth_override("test-user-wri")
    await _seed_reference_aoi("gadm", "IDN", "Indonesia", "country")
    await _create_area(client, "Indonesia Custom")

    auth_override("test-user-ds")
    res = await client.get("/api/aois?name=indonesia", headers=AUTH)
    assert res.status_code == 200, res.text
    sources = [r["source"] for r in res.json()]
    assert sources == ["gadm"]
