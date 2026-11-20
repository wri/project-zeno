from uuid import uuid4

import pytest

from src.api.services.subscription import (
    Dataset,
    NotEligibleForSubscriptionError,
    SubscriptionChannel,
    SubscriptionChannelRepository,
    SubscriptionService,
    SubscriptionTarget,
)

EMAIL = SubscriptionChannel.EMAIL
DATASETS = {Dataset.INTEGRATED_ALERTS}


class FakeRepository(SubscriptionChannelRepository):
    def __init__(self, owned=(), removed=()):
        self.saved = {}
        self.owned = list(owned)
        self.removed = list(removed)
        self.added = []

    async def set_channels(self, target, dataset, channels):
        self.saved[dataset] = channels

    async def remove_channel_for_user(self, user_id, channel):
        return self.removed

    async def find_owned_targets(self, user_id, dashboard_ids):
        return [t for t in self.owned if t.dashboard_id in dashboard_ids]

    async def add_channel(self, targets, dataset, channel):
        self.added.append((targets, dataset, channel))


def target(eligible):
    return SubscriptionTarget(
        dashboard_id=uuid4(),
        aoi_id=uuid4(),
        user_id="u1",
        eligible_for_subscription=eligible,
    )


async def test_email_on_for_an_eligible_dashboard_is_saved():
    repository = FakeRepository()

    await SubscriptionService(repository).update(
        target(eligible=True), DATASETS, {EMAIL}
    )

    assert repository.saved == {Dataset.INTEGRATED_ALERTS: {EMAIL}}


async def test_email_on_for_an_ineligible_dashboard_writes_nothing():
    repository = FakeRepository()

    with pytest.raises(NotEligibleForSubscriptionError):
        await SubscriptionService(repository).update(
            target(eligible=False), DATASETS, {EMAIL}
        )

    assert repository.saved == {}


async def test_email_off_needs_no_eligibility():
    repository = FakeRepository()

    await SubscriptionService(repository).update(
        target(eligible=False), DATASETS, set()
    )

    assert repository.saved == {Dataset.INTEGRATED_ALERTS: set()}


async def test_turning_email_off_for_a_user_returns_the_dashboards_changed():
    changed = [uuid4(), uuid4()]
    repository = FakeRepository(removed=changed)

    result = await SubscriptionService(repository).remove_for_user("u1", EMAIL)

    assert result == changed


async def test_turning_email_on_for_many_skips_ineligible_and_unowned():
    eligible, ineligible, unowned = target(True), target(False), uuid4()
    repository = FakeRepository(owned=[eligible, ineligible])

    result = await SubscriptionService(repository).add_for_user(
        "u1",
        EMAIL,
        [eligible.dashboard_id, ineligible.dashboard_id, unowned],
    )

    assert result.subscribed == [eligible.dashboard_id]
    assert set(result.skipped) == {ineligible.dashboard_id, unowned}
    assert repository.added == [([eligible], Dataset.INTEGRATED_ALERTS, EMAIL)]
