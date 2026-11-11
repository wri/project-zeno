from uuid import UUID

import pytest

from src.api.repositories import dashboard_writer
from src.api.repositories.subscription_repository import (
    PostgresSubscriptionRepository,
)
from src.api.services.subscription import (
    AoiType,
    Dataset,
    SubscriptionChannel,
    SubscriptionTarget,
)
from tests.api.test_dashboards import PARANA, _create_user

EMAIL = SubscriptionChannel.EMAIL
PROTECTED_AREA = {
    "source": "wdpa",
    "src_id": "555625",
    "subtype": "protected-area",
    "name": "Serra do Mar",
}
CONCESSION = {
    "source": "logging",
    "src_id": "cmr-123",
    "subtype": "logging",
    "name": "Concession 123",
}


async def _dashboard_with_channels(
    user_id, channels, aoi=PARANA
) -> SubscriptionTarget:
    dashboard_id = await dashboard_writer.create_dashboard(
        user_id=user_id, name=aoi["name"], aois=[aoi]
    )
    dashboard = await dashboard_writer.get_dashboard(dashboard_id)
    target = SubscriptionTarget(
        dashboard_id=dashboard.id,
        aoi_id=dashboard.aois[0].id,
        user_id=user_id,
        eligible_for_subscription=True,
    )
    await PostgresSubscriptionRepository().set_channels(
        target, Dataset.INTEGRATED_ALERTS, channels
    )
    return target


async def test_set_channels_with_none_turns_email_off():
    await _create_user("repo-set")
    target = await _dashboard_with_channels("repo-set", {EMAIL})
    repository = PostgresSubscriptionRepository()

    await repository.set_channels(target, Dataset.INTEGRATED_ALERTS, set())

    assert await repository.list_active() == []


async def test_list_active_returns_email_subscriptions():
    await _create_user("repo-active")
    emailed = await _dashboard_with_channels("repo-active", {EMAIL})
    await _dashboard_with_channels("repo-active", set())

    (subscription,) = await PostgresSubscriptionRepository().list_active()

    assert subscription.dashboard_id == emailed.dashboard_id
    assert isinstance(subscription.subscription_id, UUID)
    assert subscription.user_email == "repo-active@example.com"
    assert subscription.aoi_type == AoiType.ADMIN
    assert subscription.aoi_id == PARANA["src_id"]
    assert subscription.dataset == Dataset.INTEGRATED_ALERTS


@pytest.mark.parametrize(
    "aoi, aoi_type",
    [
        (PROTECTED_AREA, AoiType.PROTECTED_AREA),
        (CONCESSION, AoiType.CONCESSION),
    ],
)
async def test_list_active_gives_each_area_its_own_id_and_type(aoi, aoi_type):
    await _create_user(f"repo-{aoi['source']}")
    await _dashboard_with_channels(f"repo-{aoi['source']}", {EMAIL}, aoi=aoi)

    (subscription,) = await PostgresSubscriptionRepository().list_active()

    assert subscription.aoi_type == aoi_type
    assert subscription.aoi_id == aoi["src_id"]
