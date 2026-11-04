"""PUT /api/dashboards/{id}/subscriptions, the ``alerts`` field on dashboard
responses, and the subscriptions repository behind the admin listing."""

import pytest
from sqlalchemy import select

from src.api.app import app
from src.api.auth.dependencies import fetch_user_from_rw_api
from src.api.data_models import SubscriptionOrm
from src.api.repositories.subscription_repository import (
    PostgresSubscriptionRepository,
)
from src.api.services.subscription import AoiType, Dataset
from tests.api.test_dashboards import (
    AUTH,
    PARANA,
    _add_alerts_chart_widget,
    _create_dashboard,
    _create_user,
)
from tests.conftest import async_session_maker

KBA = {
    "source": "kba",
    "src_id": "16041",
    "subtype": "key-biodiversity-area",
    "name": "Serra do Mar",
}
OFF = {"integrated_alerts": {"modes": []}}
IN_APP = {"integrated_alerts": {"modes": ["in-app"]}}
BOTH = {"integrated_alerts": {"modes": ["email", "in-app"]}}


async def _put(client, dashboard_id, modes, datasets=("integrated_alerts",)):
    return await client.put(
        f"/api/dashboards/{dashboard_id}/subscriptions",
        headers=AUTH,
        json={"datasets": list(datasets), "modes": modes},
    )


async def _owned_dashboard(client, auth_override, user_id, *, eligible=True):
    """A dashboard owned by a new user, who stays signed in."""
    user = await _create_user(user_id)
    auth_override(user.id)
    if not eligible:
        return await _create_dashboard(client)
    dashboard = await _create_dashboard(client)
    await _add_alerts_chart_widget(client, dashboard["id"], user.id)
    return dashboard


def _sign_out():
    app.dependency_overrides.pop(fetch_user_from_rw_api, None)


async def _rows(dashboard_id) -> list[SubscriptionOrm]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(SubscriptionOrm)
            .where(SubscriptionOrm.dashboard_id == dashboard_id)
            .order_by(SubscriptionOrm.mode)
        )
        return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Writes and the coupling rule
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_new_dashboard_has_everything_off(client, auth_override):
    dashboard = await _owned_dashboard(client, auth_override, "subs-new")

    assert dashboard["alerts"] == OFF
    assert await _rows(dashboard["id"]) == []


@pytest.mark.asyncio
async def test_email_on_turns_in_app_on(client, auth_override):
    dashboard = await _owned_dashboard(client, auth_override, "subs-email")

    response = await _put(client, dashboard["id"], ["email"])

    assert response.status_code == 200
    assert response.json()["alerts"] == BOTH
    assert [r.mode.value for r in await _rows(dashboard["id"])] == [
        "email",
        "in-app",
    ]


@pytest.mark.asyncio
async def test_email_off_leaves_in_app_on(client, auth_override):
    dashboard = await _owned_dashboard(client, auth_override, "subs-off")
    await _put(client, dashboard["id"], ["email", "in-app"])

    response = await _put(client, dashboard["id"], ["in-app"])

    assert response.json()["alerts"] == IN_APP


@pytest.mark.asyncio
async def test_in_app_off_turns_email_off(client, auth_override):
    dashboard = await _owned_dashboard(client, auth_override, "subs-inapp")
    await _put(client, dashboard["id"], ["email", "in-app"])

    response = await _put(client, dashboard["id"], ["email"])

    assert response.json()["alerts"] == OFF
    assert await _rows(dashboard["id"]) == []


@pytest.mark.asyncio
async def test_empty_modes_turn_everything_off(client, auth_override):
    dashboard = await _owned_dashboard(client, auth_override, "subs-empty")
    await _put(client, dashboard["id"], ["email", "in-app"])

    response = await _put(client, dashboard["id"], [])

    assert response.json()["alerts"] == OFF


@pytest.mark.asyncio
async def test_setting_the_same_value_keeps_the_rows(client, auth_override):
    dashboard = await _owned_dashboard(client, auth_override, "subs-same")
    await _put(client, dashboard["id"], ["email", "in-app"])
    before = [r.id for r in await _rows(dashboard["id"])]

    response = await _put(client, dashboard["id"], ["email", "in-app"])

    assert response.status_code == 200
    assert [r.id for r in await _rows(dashboard["id"])] == before


@pytest.mark.asyncio
async def test_rows_point_at_the_dashboard_area_and_owner(
    client, auth_override
):
    dashboard = await _owned_dashboard(client, auth_override, "subs-row")

    await _put(client, dashboard["id"], ["in-app"])

    (row,) = await _rows(dashboard["id"])
    assert str(row.aoi_id) == dashboard["aois"][0]["id"]
    assert row.user_id == "subs-row"
    assert row.dataset == Dataset.INTEGRATED_ALERTS


@pytest.mark.parametrize(
    "body",
    [
        {"datasets": ["tree_cover_loss"], "modes": ["email"]},
        {"datasets": ["integrated_alerts"], "modes": ["sms"]},
        {"datasets": [], "modes": ["email"]},
    ],
)
@pytest.mark.asyncio
async def test_unknown_dataset_or_mode_is_rejected(
    client, auth_override, body
):
    dashboard = await _owned_dashboard(client, auth_override, "subs-422")

    response = await client.put(
        f"/api/dashboards/{dashboard['id']}/subscriptions",
        headers=AUTH,
        json=body,
    )

    assert response.status_code == 422
    assert await _rows(dashboard["id"]) == []


# ---------------------------------------------------------------------------
# Eligibility (email only)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_email_on_without_alerts_chart_is_409(client, auth_override):
    dashboard = await _owned_dashboard(
        client, auth_override, "subs-nochart", eligible=False
    )

    response = await _put(client, dashboard["id"], ["email", "in-app"])

    assert response.status_code == 409
    assert "integrated alerts chart" in response.json()["detail"]
    assert await _rows(dashboard["id"]) == []


@pytest.mark.asyncio
async def test_email_on_for_a_non_gadm_area_is_409(client, auth_override):
    user = await _create_user("subs-kba")
    auth_override(user.id)
    dashboard = await _create_dashboard(client, aois=[KBA])
    await _add_alerts_chart_widget(client, dashboard["id"], user.id)

    response = await _put(client, dashboard["id"], ["email"])

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_in_app_needs_no_eligibility(client, auth_override):
    dashboard = await _owned_dashboard(
        client, auth_override, "subs-inapp-any", eligible=False
    )

    response = await _put(client, dashboard["id"], ["in-app"])

    assert response.status_code == 200
    assert response.json()["alerts"] == IN_APP


@pytest.mark.asyncio
async def test_email_can_be_kept_or_turned_off_once_ineligible(
    client, auth_override
):
    dashboard = await _owned_dashboard(client, auth_override, "subs-lost")
    await _put(client, dashboard["id"], ["email"])
    (widget,) = (
        await client.get(f"/api/dashboards/{dashboard['id']}", headers=AUTH)
    ).json()["widgets"]
    await client.delete(
        f"/api/dashboards/{dashboard['id']}/widgets/{widget['id']}",
        headers=AUTH,
    )

    # Eligibility is checked only when email turns on.
    kept = await _put(client, dashboard["id"], ["email", "in-app"])
    off = await _put(client, dashboard["id"], ["in-app"])

    assert kept.status_code == 200
    assert off.json()["alerts"] == IN_APP


# ---------------------------------------------------------------------------
# Who may write and read
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_put_requires_auth(client, auth_override):
    dashboard = await _owned_dashboard(client, auth_override, "subs-anon")
    _sign_out()

    response = await client.put(
        f"/api/dashboards/{dashboard['id']}/subscriptions",
        json={"datasets": ["integrated_alerts"], "modes": ["in-app"]},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_other_users_get_404(
    client, auth_override, admin_user_factory, superuser_factory
):
    dashboard = await _owned_dashboard(client, auth_override, "subs-owner")
    other = await _create_user("subs-other")
    admin = await admin_user_factory("subs-admin@example.com")
    superuser = await superuser_factory("subs-super@example.com")

    for user in (other, admin, superuser):
        auth_override(user.id)
        response = await _put(client, dashboard["id"], ["in-app"])
        assert response.status_code == 404, user.id

    assert await _rows(dashboard["id"]) == []


@pytest.mark.asyncio
async def test_alerts_shown_to_owner_and_superuser_only(
    client, auth_override, admin_user_factory, superuser_factory
):
    dashboard = await _owned_dashboard(client, auth_override, "subs-reader")
    await _put(client, dashboard["id"], ["email"])
    await client.patch(
        f"/api/dashboards/{dashboard['id']}/public",
        headers=AUTH,
        json={"is_public": True},
    )
    url = f"/api/dashboards/{dashboard['id']}"

    owner_detail = (await client.get(url, headers=AUTH)).json()
    owner_list = (await client.get("/api/dashboards", headers=AUTH)).json()
    superuser = await superuser_factory("reader-super@example.com")
    auth_override(superuser.id)
    superuser_view = (await client.get(url, headers=AUTH)).json()
    admin = await admin_user_factory("reader-admin@example.com")
    auth_override(admin.id)
    admin_view = (await client.get(url, headers=AUTH)).json()
    other = await _create_user("subs-viewer")
    auth_override(other.id)
    other_view = (await client.get(url, headers=AUTH)).json()
    _sign_out()
    anonymous_view = (await client.get(url)).json()

    assert owner_detail["alerts"] == BOTH
    assert owner_list[0]["alerts"] == BOTH
    assert superuser_view["alerts"] == BOTH
    for view in (admin_view, other_view, anonymous_view):
        assert "alerts" not in view


# ---------------------------------------------------------------------------
# Delete and list_active
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_deleting_the_dashboard_deletes_its_subscriptions(
    client, auth_override
):
    dashboard = await _owned_dashboard(client, auth_override, "subs-delete")
    await _put(client, dashboard["id"], ["email"])

    response = await client.delete(
        f"/api/dashboards/{dashboard['id']}", headers=AUTH
    )

    assert response.status_code == 204
    assert await _rows(dashboard["id"]) == []


@pytest.mark.asyncio
async def test_list_active_returns_email_subscriptions_with_in_app(
    client, auth_override
):
    emailed = await _owned_dashboard(client, auth_override, "subs-active")
    await _put(client, emailed["id"], ["email"])
    in_app_only = await _create_dashboard(client)
    await _put(client, in_app_only["id"], ["in-app"])
    await _create_dashboard(client)

    (subscription,) = await PostgresSubscriptionRepository().list_active()

    (email_row,) = [
        r for r in await _rows(emailed["id"]) if r.mode.value == "email"
    ]
    assert subscription.subscription_id == email_row.id
    assert str(subscription.dashboard_id) == emailed["id"]
    assert subscription.user_id == "subs-active"
    assert subscription.user_email == "subs-active@example.com"
    assert subscription.aoi_type == AoiType.ADMIN
    assert subscription.aoi_id == PARANA["src_id"]
    assert subscription.dataset == Dataset.INTEGRATED_ALERTS


@pytest.mark.asyncio
async def test_admin_endpoint_lists_active_subscriptions(
    client, auth_override, superuser_factory
):
    dashboard = await _owned_dashboard(client, auth_override, "subs-admin-ep")
    await _put(client, dashboard["id"], ["email"])
    superuser = await superuser_factory("subs-ep-super@example.com")
    auth_override(superuser.id)

    response = await client.get("/api/admin/subscriptions", headers=AUTH)

    assert response.status_code == 200
    assert [s["dashboard_id"] for s in response.json()] == [dashboard["id"]]
