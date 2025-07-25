def test_custom_area_endpoints(wri_user, client):
    # list custom areas
    res = client.get(
        "/api/custom_areas/",
        headers={"Authorization": "Bearer abc123"},
    )

    assert res.status_code == 200
    assert res.json() == []

    # create a custom area
    res = client.post(
        "/api/custom_areas/",
        json={
            "name": "Test area",
            "geometry": {
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
            },
        },
        headers={"Authorization": "Bearer abc123"},
    )

    assert res.status_code == 200
    custom_area_id = res.json()["id"]
    assert custom_area_id
    assert res.json()["name"] == "Test area"
    assert res.json()["geometry"]

    # list custom areas again
    res = client.get(
        "/api/custom_areas/",
        headers={"Authorization": "Bearer abc123"},
    )

    assert res.status_code == 200
    assert len(res.json()) == 1
    assert res.json()[0]["geometry"] == {
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
    assert res.json()[0]["created_at"]
    assert res.json()[0]["name"] == "Test area"
    assert res.json()[0]["id"] == custom_area_id

    # update custom area
    res = client.patch(
        f"/api/custom_areas/{custom_area_id}",
        json={"name": "AOI #1"},
        headers={"Authorization": "Bearer abc123"},
    )

    assert res.status_code == 200
    assert res.json()["name"] == "AOI #1"
    assert res.json()["id"] == custom_area_id

    # delete custom area
    res = client.delete(
        f"/api/custom_areas/{custom_area_id}",
        headers={"Authorization": "Bearer abc123"},
    )
    assert res.status_code == 204

    # list custom areas after deletion
    res = client.get(
        "/api/custom_areas/",
        headers={"Authorization": "Bearer abc123"},
    )

    assert res.status_code == 200
    assert res.json() == []
