"""Tests for dashboard endpoints: CRUD, widgets, publish cascade, auth."""

import uuid

import pytest

from src.api.data_models import InsightOrm, UserOrm
from src.api.repositories import dashboard_access, dashboard_writer
from src.shared.config import SharedSettings
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


async def test_add_same_insight_widget_twice_conflicts(client, auth_override):
    """A retried POST cannot duplicate an insight widget: the second add
    of the same insight to the same dashboard is a 409."""
    user = await _create_user("widget-duplicate")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)
    insight = await _create_insight(user_id=user.id)

    url = f"/api/dashboards/{dashboard['id']}/widgets"
    body = {"widget_type": "insight", "insight_id": str(insight.id)}

    first = await client.post(url, headers=AUTH, json=body)
    assert first.status_code == 201

    again = await client.post(url, headers=AUTH, json=body)
    assert again.status_code == 409
    assert "already on this dashboard" in again.json()["detail"]

    rendered = await client.get(
        f"/api/dashboards/{dashboard['id']}", headers=AUTH
    )
    assert len(rendered.json()["widgets"]) == 1


async def test_map_widget_eoapi_tile_url_follows_host_rotation(
    client, auth_override, monkeypatch
):
    """eoapi tile URLs are persisted host-less and reassembled per request,
    so rotating the tile host (a config change) re-points every existing
    map widget instead of orphaning it browser-side."""
    user = await _create_user("map-widget-rotate")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)

    base = SharedSettings.eoapi_base_url.rstrip("/")
    response = await client.post(
        f"/api/dashboards/{dashboard['id']}/widgets",
        headers=AUTH,
        json={
            "widget_type": "map",
            "config": {
                "default_view": "map",
                "dataset": {
                    "dataset_name": "Tree cover loss",
                    "tile_url": f"{base}/raster/tiles/{{z}}/{{x}}/{{y}}.png",
                },
            },
        },
    )
    assert response.status_code == 201

    monkeypatch.setattr(
        SharedSettings, "eoapi_base_url", "https://eoapi-next.example.org"
    )
    rendered = await client.get(
        f"/api/dashboards/{dashboard['id']}", headers=AUTH
    )
    (widget,) = rendered.json()["widgets"]
    assert widget["config"]["dataset"]["tile_url"] == (
        "https://eoapi-next.example.org/raster/tiles/{z}/{x}/{y}.png"
    )


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
async def test_text_widget_config_validated(client, auth_override):
    user = await _create_user("text-widget")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)
    url = f"/api/dashboards/{dashboard['id']}/widgets"

    bad_bodies = [
        # No config at all.
        {"widget_type": "text"},
        # No text key.
        {"widget_type": "text", "config": {"default_view": "chart"}},
        # Non-string text.
        {"widget_type": "text", "config": {"text": 42}},
    ]
    for body in bad_bodies:
        response = await client.post(url, headers=AUTH, json=body)
        assert response.status_code == 422, body

    text_config = {"text": "## Notes\n\nDeforestation slowed in 2024."}
    response = await client.post(
        url,
        headers=AUTH,
        json={"widget_type": "text", "config": text_config},
    )
    assert response.status_code == 201

    # Config echoed verbatim on the render endpoint; no insight payload.
    rendered = await client.get(
        f"/api/dashboards/{dashboard['id']}", headers=AUTH
    )
    widgets = rendered.json()["widgets"]
    assert widgets[-1]["widget_type"] == "text"
    assert widgets[-1]["config"] == text_config
    assert widgets[-1]["insight"] is None


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


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------
async def _create_section(client, dashboard_id, **body) -> dict:
    body.setdefault("title", "Deforestation")
    response = await client.post(
        f"/api/dashboards/{dashboard_id}/sections", headers=AUTH, json=body
    )
    assert response.status_code == 201
    return response.json()["sections"][-1]


@pytest.mark.asyncio
async def test_create_sections_appends_in_order(client, auth_override):
    user = await _create_user("section-owner")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)

    await _create_section(client, dashboard["id"], title="Deforestation")
    response = await client.post(
        f"/api/dashboards/{dashboard['id']}/sections",
        headers=AUTH,
        json={"title": "Fires", "description": "Burned area over time"},
    )
    assert response.status_code == 201
    sections = response.json()["sections"]
    assert [s["title"] for s in sections] == ["Deforestation", "Fires"]
    assert [s["position"] for s in sections] == [0, 1]
    assert sections[1]["description"] == "Burned area over time"
    assert sections[0]["description"] is None


@pytest.mark.asyncio
async def test_create_section_requires_a_title(client, auth_override):
    user = await _create_user("section-title")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)

    response = await client.post(
        f"/api/dashboards/{dashboard['id']}/sections",
        headers=AUTH,
        json={"title": ""},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_section_other_user_returns_404(client, auth_override):
    owner = await _create_user("section-victim")
    other = await _create_user("section-attacker")
    auth_override(owner.id)
    dashboard = await _create_dashboard(client)

    auth_override(other.id)
    response = await client.post(
        f"/api/dashboards/{dashboard['id']}/sections",
        headers=AUTH,
        json={"title": "Deforestation"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_section_title_description_and_position(
    client, auth_override
):
    user = await _create_user("section-update")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)
    section = await _create_section(
        client, dashboard["id"], title="Trees", description="Cover loss"
    )

    response = await client.patch(
        f"/api/dashboards/{dashboard['id']}/sections/{section['id']}",
        headers=AUTH,
        json={"title": "Deforestation", "position": 4},
    )
    assert response.status_code == 200
    (updated,) = response.json()["sections"]
    assert updated["title"] == "Deforestation"
    assert updated["position"] == 4
    # An omitted description is left alone.
    assert updated["description"] == "Cover loss"

    cleared = await client.patch(
        f"/api/dashboards/{dashboard['id']}/sections/{section['id']}",
        headers=AUTH,
        json={"description": None},
    )
    assert cleared.json()["sections"][0]["description"] is None


@pytest.mark.asyncio
async def test_update_section_of_other_dashboard_returns_404(
    client, auth_override
):
    user = await _create_user("section-cross")
    auth_override(user.id)
    dashboard_a = await _create_dashboard(client, name="A")
    dashboard_b = await _create_dashboard(client, name="B")
    section = await _create_section(client, dashboard_a["id"])

    response = await client.patch(
        f"/api/dashboards/{dashboard_b['id']}/sections/{section['id']}",
        headers=AUTH,
        json={"title": "Hijacked"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_widget_created_in_a_section(client, auth_override):
    user = await _create_user("section-widget")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)
    section = await _create_section(client, dashboard["id"])
    insight = await _create_insight(user_id=user.id)

    response = await client.post(
        f"/api/dashboards/{dashboard['id']}/widgets",
        headers=AUTH,
        json={
            "widget_type": "insight",
            "insight_id": str(insight.id),
            "section_id": section["id"],
        },
    )
    assert response.status_code == 201
    (widget,) = response.json()["widgets"]
    assert widget["section_id"] == section["id"]


@pytest.mark.asyncio
async def test_widget_positions_are_per_container(client, auth_override):
    """Ungrouped widgets and a section's widgets each count from zero."""
    user = await _create_user("section-positions")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)
    section = await _create_section(client, dashboard["id"])
    url = f"/api/dashboards/{dashboard['id']}/widgets"
    note = {"widget_type": "text", "config": {"text": "note"}}

    await client.post(url, headers=AUTH, json=note)
    await client.post(url, headers=AUTH, json=note)
    response = await client.post(
        url, headers=AUTH, json={**note, "section_id": section["id"]}
    )
    assert response.status_code == 201

    widgets = response.json()["widgets"]
    ungrouped = [w for w in widgets if w["section_id"] is None]
    grouped = [w for w in widgets if w["section_id"] == section["id"]]
    assert [w["position"] for w in ungrouped] == [0, 1]
    assert [w["position"] for w in grouped] == [0]


@pytest.mark.asyncio
async def test_widget_with_unknown_section_returns_404(client, auth_override):
    user = await _create_user("section-unknown")
    auth_override(user.id)
    dashboard_a = await _create_dashboard(client, name="A")
    dashboard_b = await _create_dashboard(client, name="B")
    # A real section, but on the other dashboard.
    section = await _create_section(client, dashboard_b["id"])

    response = await client.post(
        f"/api/dashboards/{dashboard_a['id']}/widgets",
        headers=AUTH,
        json={
            "widget_type": "text",
            "config": {"text": "note"},
            "section_id": section["id"],
        },
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_move_widget_between_sections_and_back(client, auth_override):
    user = await _create_user("section-move")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)
    section = await _create_section(client, dashboard["id"])
    created = await client.post(
        f"/api/dashboards/{dashboard['id']}/widgets",
        headers=AUTH,
        json={"widget_type": "text", "config": {"text": "note"}},
    )
    widget_id = created.json()["widgets"][0]["id"]
    url = f"/api/dashboards/{dashboard['id']}/widgets/{widget_id}"

    moved = await client.patch(
        url, headers=AUTH, json={"section_id": section["id"]}
    )
    assert moved.status_code == 200
    assert moved.json()["widgets"][0]["section_id"] == section["id"]

    # An omitted section_id leaves the grouping alone.
    renamed = await client.patch(
        url, headers=AUTH, json={"config": {"text": "changed"}}
    )
    assert renamed.json()["widgets"][0]["section_id"] == section["id"]

    # An explicit null moves it back to the top level.
    ungrouped = await client.patch(
        url, headers=AUTH, json={"section_id": None}
    )
    assert ungrouped.json()["widgets"][0]["section_id"] is None


@pytest.mark.asyncio
async def test_delete_section_ungroups_its_widgets(client, auth_override):
    user = await _create_user("section-delete")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)
    section = await _create_section(client, dashboard["id"])
    await client.post(
        f"/api/dashboards/{dashboard['id']}/widgets",
        headers=AUTH,
        json={
            "widget_type": "text",
            "config": {"text": "note"},
            "section_id": section["id"],
        },
    )

    response = await client.delete(
        f"/api/dashboards/{dashboard['id']}/sections/{section['id']}",
        headers=AUTH,
    )
    assert response.status_code == 204

    rendered = await client.get(
        f"/api/dashboards/{dashboard['id']}", headers=AUTH
    )
    body = rendered.json()
    assert body["sections"] == []
    (widget,) = body["widgets"]
    assert widget["section_id"] is None
    assert widget["config"] == {"text": "note"}


@pytest.mark.asyncio
async def test_delete_dashboard_with_sections(client, auth_override):
    user = await _create_user("section-cascade")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)
    section = await _create_section(client, dashboard["id"])
    await client.post(
        f"/api/dashboards/{dashboard['id']}/widgets",
        headers=AUTH,
        json={
            "widget_type": "text",
            "config": {"text": "note"},
            "section_id": section["id"],
        },
    )

    response = await client.delete(
        f"/api/dashboards/{dashboard['id']}", headers=AUTH
    )
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_delete_section_renumbers_the_widgets_it_ungroups(
    client, auth_override
):
    user = await _create_user("section-renumber")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)
    section = await _create_section(client, dashboard["id"])
    url = f"/api/dashboards/{dashboard['id']}/widgets"

    async def _note(text, **extra):
        response = await client.post(
            url,
            headers=AUTH,
            json={"widget_type": "text", "config": {"text": text}, **extra},
        )
        assert response.status_code == 201

    await _note("top a")
    await _note("top b")
    await _note("inner a", section_id=section["id"])
    await _note("inner b", section_id=section["id"])

    response = await client.delete(
        f"/api/dashboards/{dashboard['id']}/sections/{section['id']}",
        headers=AUTH,
    )
    assert response.status_code == 204

    rendered = await client.get(
        f"/api/dashboards/{dashboard['id']}", headers=AUTH
    )
    widgets = rendered.json()["widgets"]
    assert all(w["section_id"] is None for w in widgets)
    by_text = {w["config"]["text"]: w["position"] for w in widgets}
    assert by_text == {"top a": 0, "top b": 1, "inner a": 2, "inner b": 3}


@pytest.mark.asyncio
async def test_delete_section_with_delete_widgets_removes_them(
    client, auth_override
):
    user = await _create_user("section-purge")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)
    section = await _create_section(client, dashboard["id"])
    insight = await _create_insight(user_id=user.id)
    url = f"/api/dashboards/{dashboard['id']}/widgets"

    await client.post(
        url,
        headers=AUTH,
        json={"widget_type": "text", "config": {"text": "kept"}},
    )
    await client.post(
        url,
        headers=AUTH,
        json={
            "widget_type": "insight",
            "insight_id": str(insight.id),
            "section_id": section["id"],
        },
    )

    response = await client.delete(
        f"/api/dashboards/{dashboard['id']}/sections/{section['id']}"
        "?delete_widgets=true",
        headers=AUTH,
    )
    assert response.status_code == 204

    rendered = await client.get(
        f"/api/dashboards/{dashboard['id']}", headers=AUTH
    )
    body = rendered.json()
    assert body["sections"] == []
    assert [w["config"]["text"] for w in body["widgets"]] == ["kept"]
    # The insight the deleted widget referenced survives.
    assert (
        await client.get(f"/api/insights/{insight.id}", headers=AUTH)
    ).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["", "?delete_widgets=false"])
async def test_delete_section_keeps_widgets_by_default(
    client, auth_override, query
):
    """The destructive variant is opt-in, never the default."""
    user = await _create_user(f"section-default-{len(query)}")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)
    section = await _create_section(client, dashboard["id"])
    await client.post(
        f"/api/dashboards/{dashboard['id']}/widgets",
        headers=AUTH,
        json={
            "widget_type": "text",
            "config": {"text": "note"},
            "section_id": section["id"],
        },
    )

    response = await client.delete(
        f"/api/dashboards/{dashboard['id']}/sections/{section['id']}{query}",
        headers=AUTH,
    )
    assert response.status_code == 204

    rendered = await client.get(
        f"/api/dashboards/{dashboard['id']}", headers=AUTH
    )
    body = rendered.json()
    assert body["sections"] == []
    (widget,) = body["widgets"]
    assert widget["config"] == {"text": "note"}
    assert widget["section_id"] is None


# ---------------------------------------------------------------------------
# Section types and the seal
# ---------------------------------------------------------------------------
async def _create_sealed_section(dashboard_id, *, insight_id=None) -> str:
    """Write an ``nrt-monitoring`` section the way the recipe does.

    Straight through the repository, because the REST path deliberately
    cannot create one — only the recipe endpoint can.
    """
    written = await dashboard_writer.add_section_with_widgets(
        dashboard_id,
        title="Recent disturbance",
        description="120 ha of alerts.",
        type="nrt-monitoring",
        widgets=[
            {"widget_type": "text", "config": {"text": "sealed note"}},
            *(
                [{"widget_type": "insight", "insight_id": str(insight_id)}]
                if insight_id
                else []
            ),
        ],
    )
    assert written is not None
    return written


@pytest.mark.asyncio
async def test_section_type_defaults_to_default(client, auth_override):
    user = await _create_user("section-type-default")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)

    section = await _create_section(client, dashboard["id"])

    assert section["type"] == "default"


@pytest.mark.asyncio
async def test_unknown_section_type_rejected(client, auth_override):
    user = await _create_user("section-type-unknown")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)

    response = await client.post(
        f"/api/dashboards/{dashboard['id']}/sections",
        headers=AUTH,
        json={"title": "Alerts", "type": "not-a-type"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_sealed_section_rejects_retitle_and_restate(
    client, auth_override
):
    user = await _create_user("sealed-retitle")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)
    section_id, _ = await _create_sealed_section(dashboard["id"])

    for body in ({"title": "Renamed"}, {"description": "Rewritten"}):
        response = await client.patch(
            f"/api/dashboards/{dashboard['id']}/sections/{section_id}",
            headers=AUTH,
            json=body,
        )
        assert response.status_code == 409
        assert "read-only" in response.json()["detail"]


@pytest.mark.asyncio
async def test_sealed_section_accepts_reordering(client, auth_override):
    """Position orders the dashboard; it does not change the section."""
    user = await _create_user("sealed-reorder")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)
    section_id, _ = await _create_sealed_section(dashboard["id"])

    response = await client.patch(
        f"/api/dashboards/{dashboard['id']}/sections/{section_id}",
        headers=AUTH,
        json={"position": 5},
    )
    assert response.status_code == 200
    (section,) = response.json()["sections"]
    assert section["position"] == 5
    assert section["type"] == "nrt-monitoring"


@pytest.mark.asyncio
async def test_sealed_section_rejects_new_widgets(client, auth_override):
    user = await _create_user("sealed-add-widget")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)
    section_id, _ = await _create_sealed_section(dashboard["id"])

    response = await client.post(
        f"/api/dashboards/{dashboard['id']}/widgets",
        headers=AUTH,
        json={
            "widget_type": "text",
            "config": {"text": "intruder"},
            "section_id": section_id,
        },
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_widget_cannot_leave_a_sealed_section(client, auth_override):
    user = await _create_user("sealed-move-out")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)
    _, widget_ids = await _create_sealed_section(dashboard["id"])

    response = await client.patch(
        f"/api/dashboards/{dashboard['id']}/widgets/{widget_ids[0]}",
        headers=AUTH,
        json={"section_id": None},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_widget_cannot_move_into_a_sealed_section(client, auth_override):
    user = await _create_user("sealed-move-in")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)
    section_id, _ = await _create_sealed_section(dashboard["id"])
    loose = await client.post(
        f"/api/dashboards/{dashboard['id']}/widgets",
        headers=AUTH,
        json={"widget_type": "text", "config": {"text": "outsider"}},
    )
    widget_id = loose.json()["widgets"][-1]["id"]

    response = await client.patch(
        f"/api/dashboards/{dashboard['id']}/widgets/{widget_id}",
        headers=AUTH,
        json={"section_id": section_id},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_sealed_widget_config_cannot_be_replaced(client, auth_override):
    user = await _create_user("sealed-config")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)
    _, widget_ids = await _create_sealed_section(dashboard["id"])

    response = await client.patch(
        f"/api/dashboards/{dashboard['id']}/widgets/{widget_ids[0]}",
        headers=AUTH,
        json={"config": {"text": "rewritten"}},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_sealed_widget_cannot_be_deleted_alone(client, auth_override):
    user = await _create_user("sealed-delete-widget")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)
    _, widget_ids = await _create_sealed_section(dashboard["id"])

    response = await client.delete(
        f"/api/dashboards/{dashboard['id']}/widgets/{widget_ids[0]}",
        headers=AUTH,
    )
    assert response.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["", "?delete_widgets=false"])
async def test_deleting_a_sealed_section_always_takes_its_widgets(
    client, auth_override, query
):
    """Ungrouping would leave loose, editable copies of sealed content."""
    user = await _create_user(f"sealed-delete-{len(query)}")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)
    section_id, _ = await _create_sealed_section(dashboard["id"])

    response = await client.delete(
        f"/api/dashboards/{dashboard['id']}/sections/{section_id}{query}",
        headers=AUTH,
    )
    assert response.status_code == 204

    body = (
        await client.get(f"/api/dashboards/{dashboard['id']}", headers=AUTH)
    ).json()
    assert body["sections"] == []
    assert body["widgets"] == []


@pytest.mark.asyncio
async def test_insight_in_a_sealed_section_reports_as_sealed(
    client, auth_override
):
    """The insight behind a sealed widget is that section's content.

    ``update_insight_display`` asks this before restyling, because rewriting
    the insight would change what the section shows without touching a
    single dashboard row.
    """
    user = await _create_user("sealed-insight")
    auth_override(user.id)
    insight = await _create_insight(user_id=user.id)
    loose_insight = await _create_insight(user_id=user.id)
    dashboard = await _create_dashboard(client)
    await _create_sealed_section(dashboard["id"], insight_id=insight.id)
    await client.post(
        f"/api/dashboards/{dashboard['id']}/widgets",
        headers=AUTH,
        json={"widget_type": "insight", "insight_id": str(loose_insight.id)},
    )

    assert await dashboard_access.insight_is_sealed(insight.id) is True
    # An insight on the same dashboard but outside the section stays editable.
    assert await dashboard_access.insight_is_sealed(loose_insight.id) is False
    assert await dashboard_access.insight_is_sealed(uuid.uuid4()) is False


# ---------------------------------------------------------------------------
# Layout edits inside a sealed section
# ---------------------------------------------------------------------------
#
# `config.size` ("single" | "double") is the frontend's own wide-vs-not
# setting, and `config.sizes` its per-chart map. They are layout, so a sealed
# section takes them; everything else in a config is content and does not.
async def _sealed_map_widget(client, dashboard_id) -> tuple[str, str, dict]:
    """A sealed section holding one map widget; returns ids plus its config."""
    section_id, widget_ids = await dashboard_writer.add_section_with_widgets(
        dashboard_id,
        title="Recent disturbance",
        type="nrt-monitoring",
        widgets=[
            {
                "widget_type": "map",
                "config": {
                    "default_view": "map",
                    "size": "single",
                    "dataset": {
                        "dataset_id": 11,
                        "tile_url": "https://tiles.example/{z}/{x}/{y}.png",
                        "start_date": "2026-06-04",
                        "end_date": "2026-09-02",
                    },
                },
            }
        ],
    )
    body = (
        await client.get(f"/api/dashboards/{dashboard_id}", headers=AUTH)
    ).json()
    (widget,) = body["widgets"]
    return section_id, widget_ids[0], widget["config"]


@pytest.mark.asyncio
async def test_sealed_widget_can_be_resized(client, auth_override):
    user = await _create_user("sealed-resize")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)
    _, widget_id, config = await _sealed_map_widget(client, dashboard["id"])

    response = await client.patch(
        f"/api/dashboards/{dashboard['id']}/widgets/{widget_id}",
        headers=AUTH,
        json={"config": {**config, "size": "double"}},
    )

    assert response.status_code == 200
    (widget,) = response.json()["widgets"]
    assert widget["config"]["size"] == "double"
    # The layer it shows is untouched.
    assert widget["config"]["dataset"]["dataset_id"] == 11


@pytest.mark.asyncio
async def test_sealed_widget_can_be_repositioned(client, auth_override):
    user = await _create_user("sealed-reposition")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)
    _, widget_id, _ = await _sealed_map_widget(client, dashboard["id"])

    response = await client.patch(
        f"/api/dashboards/{dashboard['id']}/widgets/{widget_id}",
        headers=AUTH,
        json={"position": 3},
    )

    assert response.status_code == 200
    assert response.json()["widgets"][0]["position"] == 3


@pytest.mark.asyncio
async def test_sealed_widget_resize_cannot_carry_a_content_change(
    client, auth_override
):
    """The whole reason the check is a diff: "resize" and "resize and swap
    the tile_url" arrive as the same shape of request."""
    user = await _create_user("sealed-resize-smuggle")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)
    _, widget_id, config = await _sealed_map_widget(client, dashboard["id"])

    smuggled = {
        **config,
        "size": "double",
        "dataset": {**config["dataset"], "tile_url": "https://evil/{z}.png"},
    }
    response = await client.patch(
        f"/api/dashboards/{dashboard['id']}/widgets/{widget_id}",
        headers=AUTH,
        json={"config": smuggled},
    )

    assert response.status_code == 409
    body = (
        await client.get(f"/api/dashboards/{dashboard['id']}", headers=AUTH)
    ).json()
    (widget,) = body["widgets"]
    assert (
        widget["config"]["dataset"]["tile_url"]
        == config["dataset"]["tile_url"]
    )
    assert widget["config"]["size"] == "single"


@pytest.mark.asyncio
async def test_sealed_widget_title_change_is_still_refused(
    client, auth_override
):
    """A title is words, not layout."""
    user = await _create_user("sealed-retitle-widget")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)
    _, widget_id, config = await _sealed_map_widget(client, dashboard["id"])

    response = await client.patch(
        f"/api/dashboards/{dashboard['id']}/widgets/{widget_id}",
        headers=AUTH,
        json={"config": {**config, "title": "My own heading"}},
    )

    assert response.status_code == 409
