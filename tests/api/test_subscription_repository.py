from uuid import UUID

from src.api.repositories import dashboard_writer
from src.api.repositories.subscription_repository import (
    PostgresSubscriptionRepository,
)
from src.api.services.subscription import (
    AoiType,
    Dataset,
    SubscriptionMode,
    SubscriptionTarget,
)
from tests.api.test_dashboards import PARANA, _create_user

EMAIL = SubscriptionMode.EMAIL
IN_APP = SubscriptionMode.IN_APP


async def _dashboard_with_modes(user_id, modes) -> SubscriptionTarget:
    dashboard_id = await dashboard_writer.create_dashboard(
        user_id=user_id, name="Paraná", aois=[PARANA]
    )
    dashboard = await dashboard_writer.get_dashboard(dashboard_id)
    target = SubscriptionTarget(
        dashboard_id=dashboard.id,
        aoi_id=dashboard.aois[0].id,
        user_id=user_id,
    )
    await PostgresSubscriptionRepository().set_modes(
        target, Dataset.INTEGRATED_ALERTS, modes
    )
    return target


async def test_set_modes_replaces_the_modes_on():
    await _create_user("repo-set")
    target = await _dashboard_with_modes("repo-set", {EMAIL, IN_APP})
    repository = PostgresSubscriptionRepository()

    await repository.set_modes(target, Dataset.INTEGRATED_ALERTS, {IN_APP})

    assert await repository.list_modes(
        target.dashboard_id, Dataset.INTEGRATED_ALERTS
    ) == {IN_APP}


async def test_list_active_returns_email_subscriptions_with_in_app():
    await _create_user("repo-active")
    emailed = await _dashboard_with_modes("repo-active", {EMAIL, IN_APP})
    await _dashboard_with_modes("repo-active", {IN_APP})

    (subscription,) = await PostgresSubscriptionRepository().list_active()

    assert subscription.dashboard_id == emailed.dashboard_id
    assert isinstance(subscription.subscription_id, UUID)
    assert subscription.user_email == "repo-active@example.com"
    assert subscription.aoi_type == AoiType.ADMIN
    assert subscription.aoi_id == PARANA["src_id"]
    assert subscription.dataset == Dataset.INTEGRATED_ALERTS
