"""Whether a dashboard can have email alerts, kept current as its widgets
change, and email turned off when it stops qualifying."""

import pytest

from src.agent.datasets.handlers.analytics_handler import INTEGRATED_ALERTS_ID
from src.api.repositories import dashboard_writer
from src.api.repositories.subscription_repository import (
    PostgresSubscriptionRepository,
)
from tests.api.test_dashboards import (
    AUTH,
    _add_alerts_chart_widget,
    _create_dashboard,
    _create_user,
)

OTHER_DATASET_ID = 1


def _layer(dataset_id):
    return {
        "dataset": {"tile_url": "/tiles/{z}/{x}/{y}", "dataset_id": dataset_id}
    }


async def _dashboard(client, dashboard_id):
    response = await client.get(
        f"/api/dashboards/{dashboard_id}", headers=AUTH
    )
    return response.json()


async def _add_layer_widget(client, dashboard_id, dataset_id, section_id=None):
    body = {"widget_type": "map", "config": _layer(dataset_id)}
    if section_id is not None:
        body["section_id"] = section_id
    response = await client.post(
        f"/api/dashboards/{dashboard_id}/widgets", headers=AUTH, json=body
    )
    assert response.status_code == 201
    return response.json()


async def _turn_email_on(client, dashboard_id):
    response = await client.put(
        f"/api/dashboards/{dashboard_id}/subscriptions",
        headers=AUTH,
        json={"datasets": ["integrated_alerts"], "modes": ["email"]},
    )
    assert response.status_code == 200


async def _owned_dashboard(client, auth_override, user_id):
    user = await _create_user(user_id)
    auth_override(user.id)
    return await _create_dashboard(client)


@pytest.mark.asyncio
async def test_new_dashboard_is_not_eligible(client, auth_override):
    dashboard = await _owned_dashboard(client, auth_override, "elig-new")

    assert dashboard["eligible_for_subscription"] is False


@pytest.mark.asyncio
async def test_integrated_alerts_chart_makes_it_eligible(
    client, auth_override
):
    dashboard = await _owned_dashboard(client, auth_override, "elig-chart")

    await _add_alerts_chart_widget(client, dashboard["id"], "elig-chart")

    assert (await _dashboard(client, dashboard["id"]))[
        "eligible_for_subscription"
    ] is True


@pytest.mark.asyncio
async def test_integrated_alerts_layer_counts_until_its_dataset_changes(
    client, auth_override
):
    dashboard = await _owned_dashboard(client, auth_override, "elig-layer")
    added = await _add_layer_widget(
        client, dashboard["id"], INTEGRATED_ALERTS_ID
    )
    (widget,) = added["widgets"]
    eligible_with_layer = added["eligible_for_subscription"]

    await client.patch(
        f"/api/dashboards/{dashboard['id']}/widgets/{widget['id']}",
        headers=AUTH,
        json={"config": _layer(OTHER_DATASET_ID)},
    )

    assert eligible_with_layer is True
    assert (await _dashboard(client, dashboard["id"]))[
        "eligible_for_subscription"
    ] is False


@pytest.mark.asyncio
async def test_removing_the_last_alerts_widget_turns_email_off(
    client, auth_override
):
    dashboard = await _owned_dashboard(client, auth_override, "elig-remove")
    await _add_alerts_chart_widget(client, dashboard["id"], "elig-remove")
    await _turn_email_on(client, dashboard["id"])
    (widget,) = (await _dashboard(client, dashboard["id"]))["widgets"]

    await client.delete(
        f"/api/dashboards/{dashboard['id']}/widgets/{widget['id']}",
        headers=AUTH,
    )

    after = await _dashboard(client, dashboard["id"])
    assert after["eligible_for_subscription"] is False
    assert after["alerts"] == {"integrated_alerts": {"modes": []}}
    assert await PostgresSubscriptionRepository().list_active() == []


@pytest.mark.parametrize(
    "delete_widgets, eligible", [(True, False), (False, True)]
)
@pytest.mark.asyncio
async def test_removing_a_section_counts_only_when_its_widgets_go(
    client, auth_override, delete_widgets, eligible
):
    dashboard = await _owned_dashboard(
        client, auth_override, f"elig-section-{delete_widgets}"
    )
    section = (
        await client.post(
            f"/api/dashboards/{dashboard['id']}/sections",
            headers=AUTH,
            json={"title": "Alerts"},
        )
    ).json()["sections"][0]
    await _add_layer_widget(
        client, dashboard["id"], INTEGRATED_ALERTS_ID, section["id"]
    )
    await _turn_email_on(client, dashboard["id"])

    await client.delete(
        f"/api/dashboards/{dashboard['id']}/sections/{section['id']}",
        headers=AUTH,
        params={"delete_widgets": delete_widgets},
    )

    after = await _dashboard(client, dashboard["id"])
    assert after["eligible_for_subscription"] is eligible
    assert after["alerts"]["integrated_alerts"]["modes"] == (
        ["email"] if eligible else []
    )


@pytest.mark.asyncio
async def test_template_section_with_an_alerts_layer_makes_it_eligible(
    client, auth_override
):
    dashboard = await _owned_dashboard(client, auth_override, "elig-template")

    await dashboard_writer.add_section_with_widgets(
        dashboard["id"],
        title="Alerts",
        description=None,
        widgets=[
            dashboard_writer.SectionWidget(
                widget_type="map", config=_layer(INTEGRATED_ALERTS_ID)
            )
        ],
        user_id="elig-template",
    )

    assert (await _dashboard(client, dashboard["id"]))[
        "eligible_for_subscription"
    ] is True


@pytest.mark.asyncio
async def test_eligibility_changes_keep_the_updated_time(
    client, auth_override
):
    dashboard = await _owned_dashboard(client, auth_override, "elig-time")

    await _add_alerts_chart_widget(client, dashboard["id"], "elig-time")

    after = await _dashboard(client, dashboard["id"])
    assert after["eligible_for_subscription"] is True
    assert after["updated_at"] == dashboard["updated_at"]
