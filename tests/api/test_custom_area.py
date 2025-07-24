def test_create_custom_area(wri_user, client):
    wri_user
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
    assert res.json()["id"]
