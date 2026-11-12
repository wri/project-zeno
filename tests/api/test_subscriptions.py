"""Subscribing dashboards to notification emails, and who can see it."""

import pytest
from sqlalchemy import select

from src.api.app import app
from src.api.auth.dependencies import fetch_user_from_rw_api
from src.api.data_models import SubscriptionOrm
from src.api.services.subscription import Dataset
from tests.api.test_dashboards import (
    AUTH,
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
OFF = {"integrated_alerts": {"channels": []}}
EMAIL_ON = {"integrated_alerts": {"channels": ["email"]}}


async def _put(
    client, dashboard_id, channels, datasets=("integrated_alerts",)
):
    return await client.put(
        f"/api/dashboards/{dashboard_id}/subscriptions",
        headers=AUTH,
        json={"datasets": list(datasets), "channels": channels},
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
            .order_by(SubscriptionOrm.channel)
        )
        return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_new_dashboard_has_email_off(client, auth_override):
    dashboard = await _owned_dashboard(client, auth_override, "subs-new")

    assert dashboard["subscriptions"] == OFF
    assert await _rows(dashboard["id"]) == []


@pytest.mark.asyncio
async def test_email_on_and_off(client, auth_override):
    dashboard = await _owned_dashboard(client, auth_override, "subs-email")

    on = await _put(client, dashboard["id"], ["email"])
    off = await _put(client, dashboard["id"], [])

    assert on.status_code == 200
    assert on.json()["subscriptions"] == EMAIL_ON
    assert off.json()["subscriptions"] == OFF
    assert await _rows(dashboard["id"]) == []


@pytest.mark.asyncio
async def test_setting_the_same_value_keeps_the_row(client, auth_override):
    dashboard = await _owned_dashboard(client, auth_override, "subs-same")
    await _put(client, dashboard["id"], ["email"])
    before = [r.id for r in await _rows(dashboard["id"])]

    response = await _put(client, dashboard["id"], ["email"])

    assert response.status_code == 200
    assert [r.id for r in await _rows(dashboard["id"])] == before


@pytest.mark.asyncio
async def test_rows_point_at_the_dashboard_area_and_owner(
    client, auth_override
):
    dashboard = await _owned_dashboard(client, auth_override, "subs-row")

    await _put(client, dashboard["id"], ["email"])

    (row,) = await _rows(dashboard["id"])
    assert str(row.aoi_id) == dashboard["aois"][0]["id"]
    assert row.user_id == "subs-row"
    assert row.dataset == Dataset.INTEGRATED_ALERTS


@pytest.mark.parametrize(
    "body",
    [
        {"datasets": ["tree_cover_loss"], "channels": ["email"]},
        {"datasets": ["integrated_alerts"], "channels": ["in-app"]},
    ],
)
@pytest.mark.asyncio
async def test_unknown_dataset_or_channel_is_rejected(
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
# Eligibility
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_email_on_without_alerts_chart_is_409(client, auth_override):
    dashboard = await _owned_dashboard(
        client, auth_override, "subs-nochart", eligible=False
    )

    response = await _put(client, dashboard["id"], ["email"])

    assert response.status_code == 409
    assert "integrated alerts" in response.json()["detail"]
    assert await _rows(dashboard["id"]) == []


@pytest.mark.asyncio
async def test_email_on_for_a_non_admin_area(client, auth_override):
    user = await _create_user("subs-kba")
    auth_override(user.id)
    dashboard = await _create_dashboard(client, aois=[KBA])
    await _add_alerts_chart_widget(client, dashboard["id"], user.id)

    response = await _put(client, dashboard["id"], ["email"])

    assert response.status_code == 200
    assert response.json()["subscriptions"] == EMAIL_ON


# ---------------------------------------------------------------------------
# Who may write and read
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_put_requires_auth(client, auth_override):
    dashboard = await _owned_dashboard(client, auth_override, "subs-anon")
    _sign_out()

    response = await client.put(
        f"/api/dashboards/{dashboard['id']}/subscriptions",
        json={"datasets": ["integrated_alerts"], "channels": ["email"]},
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
        response = await _put(client, dashboard["id"], ["email"])
        assert response.status_code == 404, user.id

    assert await _rows(dashboard["id"]) == []


@pytest.mark.asyncio
async def test_subscriptions_shown_to_owner_and_superuser_only(
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

    assert owner_detail["subscriptions"] == EMAIL_ON
    assert owner_list[0]["subscriptions"] == EMAIL_ON
    assert superuser_view["subscriptions"] == EMAIL_ON
    for view in (admin_view, other_view, anonymous_view):
        assert "subscriptions" not in view
        assert view["eligible_for_subscription"] is True


# ---------------------------------------------------------------------------
# Delete
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


# ---------------------------------------------------------------------------
# Bulk
# ---------------------------------------------------------------------------
async def _delete_all(client, channel="email"):
    return await client.delete(
        "/api/subscriptions", headers=AUTH, params={"channel": channel}
    )


async def _put_many(client, dashboard_ids, channel="email"):
    return await client.put(
        "/api/subscriptions",
        headers=AUTH,
        json={"channel": channel, "dashboard_ids": dashboard_ids},
    )


async def _another_dashboard(client, user_id):
    dashboard = await _create_dashboard(client)
    await _add_alerts_chart_widget(client, dashboard["id"], user_id)
    return dashboard


@pytest.mark.asyncio
async def test_turn_off_all_changes_only_the_callers_email_rows(
    client, auth_override
):
    first = await _owned_dashboard(client, auth_override, "bulk-off-a")
    second = await _another_dashboard(client, "bulk-off-a")
    for dashboard in (first, second):
        await _put(client, dashboard["id"], ["email"])
    off = await _owned_dashboard(client, auth_override, "bulk-off-b")
    await _put(client, off["id"], ["email"])
    auth_override("bulk-off-a")

    response = await _delete_all(client)

    assert response.status_code == 200
    assert set(response.json()["dashboard_ids"]) == {
        first["id"],
        second["id"],
    }
    assert await _rows(first["id"]) == []
    assert await _rows(second["id"]) == []
    assert len(await _rows(off["id"])) == 1


@pytest.mark.asyncio
async def test_turn_off_all_with_nothing_on_changes_nothing(
    client, auth_override
):
    await _owned_dashboard(client, auth_override, "bulk-off-none")

    response = await _delete_all(client)

    assert response.status_code == 200
    assert response.json()["dashboard_ids"] == []


@pytest.mark.asyncio
async def test_turn_off_all_rejects_other_channels(client, auth_override):
    dashboard = await _owned_dashboard(client, auth_override, "bulk-off-422")
    await _put(client, dashboard["id"], ["email"])

    response = await _delete_all(client, channel="in-app")

    assert response.status_code == 422
    assert len(await _rows(dashboard["id"])) == 1


@pytest.mark.asyncio
async def test_bulk_endpoints_require_auth(client, auth_override):
    dashboard = await _owned_dashboard(client, auth_override, "bulk-anon")
    _sign_out()

    assert (await _delete_all(client)).status_code == 401
    assert (await _put_many(client, [dashboard["id"]])).status_code == 401


@pytest.mark.asyncio
async def test_turn_on_many_skips_ineligible_and_other_users_dashboards(
    client, auth_override
):
    mine = await _owned_dashboard(client, auth_override, "bulk-on-a")
    ineligible = await _create_dashboard(client)
    theirs = await _owned_dashboard(client, auth_override, "bulk-on-b")
    auth_override("bulk-on-a")

    response = await _put_many(
        client, [mine["id"], ineligible["id"], theirs["id"]]
    )

    assert response.status_code == 200
    assert response.json()["dashboard_ids"] == [mine["id"]]
    assert set(response.json()["skipped"]) == {ineligible["id"], theirs["id"]}
    assert len(await _rows(mine["id"])) == 1
    assert await _rows(ineligible["id"]) == []
    assert await _rows(theirs["id"]) == []


@pytest.mark.asyncio
async def test_undoing_turn_off_all_restores_the_same_dashboards(
    client, auth_override
):
    first = await _owned_dashboard(client, auth_override, "bulk-undo")
    second = await _another_dashboard(client, "bulk-undo")
    await _put(client, first["id"], ["email"])

    changed = (await _delete_all(client)).json()["dashboard_ids"]
    await _put_many(client, changed)

    assert len(await _rows(first["id"])) == 1
    assert await _rows(second["id"]) == []
