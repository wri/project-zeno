import pytest


@pytest.mark.asyncio
async def test_custom_area_endpoints(auth_override, client):
    auth_override("test-user-wri")
    # list custom areas
    res = await client.get(
        "/api/custom_areas",
        headers={"Authorization": "Bearer abc123"},
    )

    assert res.status_code == 200
    assert res.json() == []

    # create a custom area
    res = await client.post(
        "/api/custom_areas",
        json={
            "name": "Test area",
            "geometries": [
                {
                    "coordinates": [
                        [
                            [29.2263174, -1.641965],
                            [29.2263174, -1.665582],
                            [29.2301511, -1.665582],
                            [29.2301511, -1.641965],
                            [29.2263174, -1.641965],
                        ]
                    ],
                    "type": "Polygon",
                }
            ],
        },
        headers={"Authorization": "Bearer abc123"},
    )

    assert res.status_code == 200
    custom_area_id = res.json()["id"]
    assert custom_area_id
    assert res.json()["name"] == "Test area"
    assert res.json()["geometries"] == [
        {
            "coordinates": [
                [
                    [29.2263174, -1.641965],
                    [29.2263174, -1.665582],
                    [29.2301511, -1.665582],
                    [29.2301511, -1.641965],
                    [29.2263174, -1.641965],
                ]
            ],
            "type": "Polygon",
        }
    ]

    # list custom areas again
    res = await client.get(
        "/api/custom_areas",
        headers={"Authorization": "Bearer abc123"},
    )

    assert res.status_code == 200
    assert len(res.json()) == 1
    assert res.json()[0]["geometries"] == [
        {
            "coordinates": [
                [
                    [29.2263174, -1.641965],
                    [29.2263174, -1.665582],
                    [29.2301511, -1.665582],
                    [29.2301511, -1.641965],
                    [29.2263174, -1.641965],
                ]
            ],
            "type": "Polygon",
        }
    ]
    assert res.json()[0]["created_at"]
    assert res.json()[0]["name"] == "Test area"
    assert res.json()[0]["id"] == custom_area_id

    # update custom area
    res = await client.patch(
        f"/api/custom_areas/{custom_area_id}",
        json={"name": "AOI #1"},
        headers={"Authorization": "Bearer abc123"},
    )

    assert res.status_code == 200
    assert res.json()["name"] == "AOI #1"
    assert res.json()["id"] == custom_area_id

    # delete custom area
    res = await client.delete(
        f"/api/custom_areas/{custom_area_id}",
        headers={"Authorization": "Bearer abc123"},
    )
    assert res.status_code == 204

    # list custom areas after deletion
    res = await client.get(
        "/api/custom_areas",
        headers={"Authorization": "Bearer abc123"},
    )

    assert res.status_code == 200
    assert res.json() == []


_SQUARE = {
    "type": "Polygon",
    "coordinates": [
        [[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]]
    ],
}

AUTH = {"Authorization": "Bearer abc123"}


async def _create(client, name):
    res = await client.post(
        "/api/custom_areas",
        json={"name": name, "geometries": [_SQUARE]},
        headers=AUTH,
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


@pytest.mark.asyncio
async def test_list_paginates_newest_first(auth_override, client):
    auth_override("test-user-wri")
    for name in ("First", "Second", "Third", "Fourth", "Fifth"):
        await _create(client, name)

    res = await client.get("/api/custom_areas?limit=2", headers=AUTH)
    assert res.status_code == 200, res.text
    assert [a["name"] for a in res.json()] == ["Fifth", "Fourth"]
    assert res.headers["X-Next-Offset"] == "2"

    res = await client.get("/api/custom_areas?limit=2&offset=2", headers=AUTH)
    assert [a["name"] for a in res.json()] == ["Third", "Second"]
    assert res.headers["X-Next-Offset"] == "4"

    # The last page is short, and it carries no next-offset header.
    res = await client.get("/api/custom_areas?limit=2&offset=4", headers=AUTH)
    assert [a["name"] for a in res.json()] == ["First"]
    assert "X-Next-Offset" not in res.headers


@pytest.mark.asyncio
async def test_list_full_page_without_more_has_no_header(
    auth_override, client
):
    """A page that is exactly full must not promise a next page."""
    auth_override("test-user-wri")
    await _create(client, "One")
    await _create(client, "Two")

    res = await client.get("/api/custom_areas?limit=2", headers=AUTH)
    assert len(res.json()) == 2
    assert "X-Next-Offset" not in res.headers


@pytest.mark.asyncio
async def test_list_offset_past_the_end_is_empty(auth_override, client):
    auth_override("test-user-wri")
    await _create(client, "Only")

    res = await client.get("/api/custom_areas?offset=5", headers=AUTH)
    assert res.status_code == 200
    assert res.json() == []
    assert "X-Next-Offset" not in res.headers


@pytest.mark.asyncio
async def test_list_rejects_out_of_range_paging(auth_override, client):
    auth_override("test-user-wri")
    for query in ("limit=0", "limit=101", "offset=-1"):
        res = await client.get(f"/api/custom_areas?{query}", headers=AUTH)
        assert res.status_code == 422, query
