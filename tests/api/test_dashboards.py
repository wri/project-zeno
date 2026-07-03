"""Tests for dashboard endpoints: CRUD, widgets, publish cascade, auth."""

import uuid

import pytest

from src.api.data_models import InsightOrm, UserOrm
from tests.conftest import async_session_maker

PARANA = {
    "source": "gadm",
    "src_id": "BRA.16_1",
    "subtype": "state-province",
    "name": "Paraná",
}
BRAZIL = {
    "source": "gadm",
    "src_id": "BRA",
    "subtype": "country",
    "name": "Brazil",
}
AUTH = {"Authorization": "Bearer t"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _create_user(user_id: str) -> UserOrm:
    async with async_session_maker() as session:
        user = UserOrm(
            id=user_id, name=user_id, email=f"{user_id}@example.com"
        )
        session.add(user)
        await session.commit()
        return user


async def _create_insight(
    *, user_id: str | None, is_public: bool = False
) -> InsightOrm:
    async with async_session_maker() as session:
        row = InsightOrm(
            user_id=user_id,
            thread_id="thread-1",
            insight_text="Sample insight text",
            is_public=is_public,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


async def _create_dashboard(client, *, name=None, aois=None) -> dict:
    body = {"aois": aois or [PARANA]}
    if name:
        body["name"] = name
    response = await client.post("/api/dashboards", headers=AUTH, json=body)
    assert response.status_code == 201
    return response.json()


# ---------------------------------------------------------------------------
# POST /api/dashboards
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_create_dashboard_requires_auth(client):
    response = await client.post("/api/dashboards", json={"aois": [PARANA]})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_dashboard_name_defaults_to_aoi(client, auth_override):
    user = await _create_user("dash-creator")
    auth_override(user.id)

    body = await _create_dashboard(client)
    assert body["name"] == "Paraná"
    assert body["user_id"] == user.id
    assert body["is_public"] is False
    assert body["widgets"] == []
    assert len(body["aois"]) == 1
    assert body["aois"][0]["src_id"] == "BRA.16_1"


@pytest.mark.asyncio
async def test_create_dashboard_two_aois_rejected(client, auth_override):
    """The MVP single-area constraint is API validation, not schema."""
    user = await _create_user("dash-multi")
    auth_override(user.id)

    response = await client.post(
        "/api/dashboards",
        headers=AUTH,
        json={"aois": [PARANA, BRAZIL]},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_dashboard_zero_aois_rejected(client, auth_override):
    user = await _create_user("dash-empty")
    auth_override(user.id)

    response = await client.post(
        "/api/dashboards", headers=AUTH, json={"aois": []}
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/dashboards (list)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_list_dashboards_own_only_newest_first(client, auth_override):
    owner = await _create_user("list-owner")
    other = await _create_user("list-other")

    auth_override(other.id)
    await _create_dashboard(client, name="Other's")

    auth_override(owner.id)
    first = await _create_dashboard(client, name="First")
    second = await _create_dashboard(client, name="Second")

    response = await client.get("/api/dashboards", headers=AUTH)
    assert response.status_code == 200
    assert [d["id"] for d in response.json()] == [
        second["id"],
        first["id"],
    ]


# ---------------------------------------------------------------------------
# GET /api/dashboards/{id}
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_own_private_dashboard(client, auth_override):
    user = await _create_user("get-owner")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)

    response = await client.get(
        f"/api/dashboards/{dashboard['id']}", headers=AUTH
    )
    assert response.status_code == 200
    assert response.json()["id"] == dashboard["id"]


@pytest.mark.asyncio
async def test_get_private_dashboard_other_user_returns_404(
    client, auth_override
):
    owner = await _create_user("private-owner")
    other = await _create_user("private-other")
    auth_override(owner.id)
    dashboard = await _create_dashboard(client)

    auth_override(other.id)
    response = await client.get(
        f"/api/dashboards/{dashboard['id']}", headers=AUTH
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_private_dashboard_no_auth_returns_401(
    client, auth_override
):
    user = await _create_user("noauth-owner")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)

    from src.api.app import app
    from src.api.auth.dependencies import fetch_user_from_rw_api

    app.dependency_overrides.pop(fetch_user_from_rw_api, None)
    response = await client.get(f"/api/dashboards/{dashboard['id']}")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_nonexistent_dashboard_returns_404(client, auth_override):
    await _create_user("get-miss")
    auth_override("get-miss")

    response = await client.get(
        f"/api/dashboards/{uuid.uuid4()}", headers=AUTH
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_admin_can_access_private_dashboard(
    client, auth_override, admin_user_factory
):
    owner = await _create_user("admin-target-owner")
    admin = await admin_user_factory("dash-admin@example.com")
    auth_override(owner.id)
    dashboard = await _create_dashboard(client)

    auth_override(admin.id)
    response = await client.get(
        f"/api/dashboards/{dashboard['id']}", headers=AUTH
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_dashboard_expands_insight_widgets(client, auth_override):
    user = await _create_user("expand-owner")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)
    insight = await _create_insight(user_id=user.id)

    response = await client.post(
        f"/api/dashboards/{dashboard['id']}/widgets",
        headers=AUTH,
        json={"widget_type": "insight", "insight_id": str(insight.id)},
    )
    assert response.status_code == 201

    response = await client.get(
        f"/api/dashboards/{dashboard['id']}", headers=AUTH
    )
    widget = response.json()["widgets"][0]
    assert widget["widget_type"] == "insight"
    assert widget["insight_id"] == str(insight.id)
    # Same shape the insights endpoints return, nested in the widget.
    assert widget["insight"]["insight_text"] == "Sample insight text"
    assert widget["insight"]["id"] == str(insight.id)


# ---------------------------------------------------------------------------
# PATCH /api/dashboards/{id}
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_rename_dashboard(client, auth_override):
    user = await _create_user("rename-owner")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)

    response = await client.patch(
        f"/api/dashboards/{dashboard['id']}",
        headers=AUTH,
        json={"name": "Renamed", "description": "With description"},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"
    assert response.json()["description"] == "With description"


@pytest.mark.asyncio
async def test_rename_dashboard_other_user_returns_404(client, auth_override):
    owner = await _create_user("rename-victim")
    other = await _create_user("rename-attacker")
    auth_override(owner.id)
    dashboard = await _create_dashboard(client)

    auth_override(other.id)
    response = await client.patch(
        f"/api/dashboards/{dashboard['id']}",
        headers=AUTH,
        json={"name": "Hijacked"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/dashboards/{id}/public
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_publish_cascades_to_insights_and_lists_them(
    client, auth_override
):
    user = await _create_user("publish-owner")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)
    private_insight = await _create_insight(user_id=user.id)
    public_insight = await _create_insight(user_id=user.id, is_public=True)
    for insight in (private_insight, public_insight):
        await client.post(
            f"/api/dashboards/{dashboard['id']}/widgets",
            headers=AUTH,
            json={"widget_type": "insight", "insight_id": str(insight.id)},
        )

    response = await client.patch(
        f"/api/dashboards/{dashboard['id']}/public",
        headers=AUTH,
        json={"is_public": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["is_public"] is True
    # Only the insight that actually flipped is listed.
    assert body["publicized_insight_ids"] == [str(private_insight.id)]

    # The dashboard and the cascaded insight are now readable anonymously.
    from src.api.app import app
    from src.api.auth.dependencies import fetch_user_from_rw_api

    app.dependency_overrides.pop(fetch_user_from_rw_api, None)
    anon = await client.get(f"/api/dashboards/{dashboard['id']}")
    assert anon.status_code == 200
    assert all(
        widget["insight"] is not None for widget in anon.json()["widgets"]
    )
    assert (
        await client.get(f"/api/insights/{private_insight.id}")
    ).status_code == 200


@pytest.mark.asyncio
async def test_unpublish_does_not_cascade(client, auth_override):
    user = await _create_user("unpublish-owner")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)
    insight = await _create_insight(user_id=user.id)
    await client.post(
        f"/api/dashboards/{dashboard['id']}/widgets",
        headers=AUTH,
        json={"widget_type": "insight", "insight_id": str(insight.id)},
    )
    await client.patch(
        f"/api/dashboards/{dashboard['id']}/public",
        headers=AUTH,
        json={"is_public": True},
    )

    response = await client.patch(
        f"/api/dashboards/{dashboard['id']}/public",
        headers=AUTH,
        json={"is_public": False},
    )
    assert response.status_code == 200
    assert response.json()["is_public"] is False
    assert response.json()["publicized_insight_ids"] == []

    # The insight stays public — it may be shared elsewhere.
    insight_response = await client.get(
        f"/api/insights/{insight.id}", headers=AUTH
    )
    assert insight_response.json()["is_public"] is True


@pytest.mark.asyncio
async def test_publish_other_user_returns_404(client, auth_override):
    owner = await _create_user("publish-victim")
    other = await _create_user("publish-attacker")
    auth_override(owner.id)
    dashboard = await _create_dashboard(client)

    auth_override(other.id)
    response = await client.patch(
        f"/api/dashboards/{dashboard['id']}/public",
        headers=AUTH,
        json={"is_public": True},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Widget endpoints
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_insight_widget_requires_insight_id(client, auth_override):
    user = await _create_user("widget-no-insight")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)

    response = await client.post(
        f"/api/dashboards/{dashboard['id']}/widgets",
        headers=AUTH,
        json={"widget_type": "insight"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_widget_type_validated(client, auth_override):
    user = await _create_user("widget-bad-type")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)

    response = await client.post(
        f"/api/dashboards/{dashboard['id']}/widgets",
        headers=AUTH,
        json={"widget_type": "carousel"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_widget_insight_must_be_visible(client, auth_override):
    owner = await _create_user("widget-owner")
    other = await _create_user("widget-other")
    someone_elses_insight = await _create_insight(user_id=other.id)
    auth_override(owner.id)
    dashboard = await _create_dashboard(client)

    response = await client.post(
        f"/api/dashboards/{dashboard['id']}/widgets",
        headers=AUTH,
        json={
            "widget_type": "insight",
            "insight_id": str(someone_elses_insight.id),
        },
    )
    assert response.status_code == 404

    # A public insight owned by someone else is fine.
    public_insight = await _create_insight(user_id=other.id, is_public=True)
    response = await client.post(
        f"/api/dashboards/{dashboard['id']}/widgets",
        headers=AUTH,
        json={
            "widget_type": "insight",
            "insight_id": str(public_insight.id),
        },
    )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_map_widget_config_accepted(client, auth_override):
    user = await _create_user("map-widget-ok")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)

    dataset_config = {
        "default_view": "map",
        "dataset": {
            "dataset_id": 4,
            "dataset_name": "Tree cover loss",
            "tile_url": "https://tiles.example.com/{z}/{x}/{y}.png",
            "context_layer": None,
            "context_layers": [],
            "parameters": None,
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
        },
    }
    response = await client.post(
        f"/api/dashboards/{dashboard['id']}/widgets",
        headers=AUTH,
        json={"widget_type": "map", "config": dataset_config},
    )
    assert response.status_code == 201

    imagery_config = {
        "default_view": "map",
        "imagery": {
            "tile_url": "https://tiles.example.com/mosaic/{z}/{x}/{y}.png",
            "tilejson_url": "https://tiles.example.com/tilejson.json",
            "mosaic_id": "abc123",
            "target_date": "2024-06-01",
            "window_days": 7,
            "max_cloud_cover": 20,
            "aoi_names": ["Paraná"],
        },
    }
    response = await client.post(
        f"/api/dashboards/{dashboard['id']}/widgets",
        headers=AUTH,
        json={"widget_type": "map", "config": imagery_config},
    )
    assert response.status_code == 201

    # Configs are echoed verbatim on the render endpoint; no insight payload.
    rendered = await client.get(
        f"/api/dashboards/{dashboard['id']}", headers=AUTH
    )
    widgets = rendered.json()["widgets"]
    assert [w["config"] for w in widgets] == [dataset_config, imagery_config]
    assert all(w["insight"] is None for w in widgets)


@pytest.mark.asyncio
async def test_map_widget_config_validated(client, auth_override):
    user = await _create_user("map-widget-bad")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)
    url = f"/api/dashboards/{dashboard['id']}/widgets"
    layer = {"tile_url": "https://t/{z}"}

    bad_bodies = [
        # No config at all.
        {"widget_type": "map"},
        # Neither dataset nor imagery.
        {"widget_type": "map", "config": {"default_view": "map"}},
        # Both at once.
        {
            "widget_type": "map",
            "config": {"dataset": layer, "imagery": layer},
        },
        # Missing tile_url.
        {"widget_type": "map", "config": {"dataset": {"dataset_id": 4}}},
    ]
    for body in bad_bodies:
        response = await client.post(url, headers=AUTH, json=body)
        assert response.status_code == 422, body

    # Insight widgets keep their plain presentation config.
    insight = await _create_insight(user_id=user.id)
    response = await client.post(
        url,
        headers=AUTH,
        json={
            "widget_type": "insight",
            "insight_id": str(insight.id),
            "config": {"default_view": "chart"},
        },
    )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_widget_add_reorder_remove(client, auth_override):
    user = await _create_user("widget-lifecycle")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)
    insight = await _create_insight(user_id=user.id)

    created = await client.post(
        f"/api/dashboards/{dashboard['id']}/widgets",
        headers=AUTH,
        json={"widget_type": "insight", "insight_id": str(insight.id)},
    )
    map_widget = await client.post(
        f"/api/dashboards/{dashboard['id']}/widgets",
        headers=AUTH,
        json={
            "widget_type": "map",
            "config": {
                "default_view": "map",
                "dataset": {"dataset_id": 4, "tile_url": "https://t/{z}"},
            },
        },
    )
    widgets = map_widget.json()["widgets"]
    assert [w["position"] for w in widgets] == [0, 1]
    insight_widget_id = created.json()["widgets"][0]["id"]
    map_widget_id = widgets[1]["id"]

    # Reorder.
    response = await client.patch(
        f"/api/dashboards/{dashboard['id']}/widgets/{map_widget_id}",
        headers=AUTH,
        json={"position": 0},
    )
    assert response.status_code == 200

    # Remove; the insight itself survives.
    response = await client.delete(
        f"/api/dashboards/{dashboard['id']}/widgets/{insight_widget_id}",
        headers=AUTH,
    )
    assert response.status_code == 204
    remaining = await client.get(
        f"/api/dashboards/{dashboard['id']}", headers=AUTH
    )
    assert [w["id"] for w in remaining.json()["widgets"]] == [map_widget_id]
    assert (
        await client.get(f"/api/insights/{insight.id}", headers=AUTH)
    ).status_code == 200


@pytest.mark.asyncio
async def test_widget_of_other_dashboard_returns_404(client, auth_override):
    user = await _create_user("widget-cross")
    auth_override(user.id)
    dashboard_a = await _create_dashboard(client, name="A")
    dashboard_b = await _create_dashboard(client, name="B")
    insight = await _create_insight(user_id=user.id)
    created = await client.post(
        f"/api/dashboards/{dashboard_a['id']}/widgets",
        headers=AUTH,
        json={"widget_type": "insight", "insight_id": str(insight.id)},
    )
    widget_id = created.json()["widgets"][0]["id"]

    response = await client.patch(
        f"/api/dashboards/{dashboard_b['id']}/widgets/{widget_id}",
        headers=AUTH,
        json={"position": 3},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/dashboards/{id}
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_delete_dashboard_leaves_insights(client, auth_override):
    user = await _create_user("delete-owner")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)
    insight = await _create_insight(user_id=user.id)
    await client.post(
        f"/api/dashboards/{dashboard['id']}/widgets",
        headers=AUTH,
        json={"widget_type": "insight", "insight_id": str(insight.id)},
    )

    response = await client.delete(
        f"/api/dashboards/{dashboard['id']}", headers=AUTH
    )
    assert response.status_code == 204
    assert (
        await client.get(f"/api/dashboards/{dashboard['id']}", headers=AUTH)
    ).status_code == 404
    assert (
        await client.get(f"/api/insights/{insight.id}", headers=AUTH)
    ).status_code == 200


@pytest.mark.asyncio
async def test_delete_dashboard_other_user_returns_404(client, auth_override):
    owner = await _create_user("delete-victim")
    other = await _create_user("delete-attacker")
    auth_override(owner.id)
    dashboard = await _create_dashboard(client)

    auth_override(other.id)
    response = await client.delete(
        f"/api/dashboards/{dashboard['id']}", headers=AUTH
    )
    assert response.status_code == 404
