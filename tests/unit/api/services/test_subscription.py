from uuid import uuid4

import pytest

from src.api.services.subscription import (
    Dataset,
    EmailAlertsUnavailableError,
    EmailEligibility,
    SubscriptionMode,
    SubscriptionModeRepository,
    SubscriptionService,
    SubscriptionTarget,
    modes_to_store,
)

EMAIL = SubscriptionMode.EMAIL
IN_APP = SubscriptionMode.IN_APP


@pytest.mark.parametrize(
    "requested, stored",
    [
        ({EMAIL}, {EMAIL, IN_APP}),
        ({EMAIL, IN_APP}, {EMAIL, IN_APP}),
        ({IN_APP}, {IN_APP}),
        (set(), set()),
    ],
)
def test_modes_to_store(requested, stored):
    assert modes_to_store(requested) == stored


class FakeRepository(SubscriptionModeRepository):
    def __init__(self, current):
        self.current = current
        self.saved = {}

    async def list_modes(self, dashboard_id, dataset):
        return set(self.current)

    async def set_modes(self, target, dataset, modes):
        self.saved[dataset] = modes


class FakeEligibility(EmailEligibility):
    def __init__(self, allowed):
        self.allowed = allowed
        self.asked = False

    async def allows_email(self, dashboard_id):
        self.asked = True
        return self.allowed


def service(current, allowed):
    repository = FakeRepository(current)
    eligibility = FakeEligibility(allowed)
    return (
        SubscriptionService(repository, eligibility),
        repository,
        eligibility,
    )


TARGET = SubscriptionTarget(dashboard_id=uuid4(), aoi_id=uuid4(), user_id="u1")
DATASETS = {Dataset.INTEGRATED_ALERTS}


async def test_email_on_stores_both_modes():
    subscriptions, repository, _ = service(set(), allowed=True)

    await subscriptions.update(TARGET, DATASETS, {EMAIL})

    assert repository.saved == {Dataset.INTEGRATED_ALERTS: {EMAIL, IN_APP}}


async def test_email_on_for_an_ineligible_dashboard_writes_nothing():
    subscriptions, repository, _ = service({IN_APP}, allowed=False)

    with pytest.raises(EmailAlertsUnavailableError):
        await subscriptions.update(TARGET, DATASETS, {EMAIL, IN_APP})

    assert repository.saved == {}


async def test_eligibility_is_only_checked_when_email_turns_on():
    subscriptions, repository, eligibility = service(
        {EMAIL, IN_APP}, allowed=False
    )

    await subscriptions.update(TARGET, DATASETS, {EMAIL, IN_APP})
    await subscriptions.update(TARGET, DATASETS, {IN_APP})

    assert not eligibility.asked
    assert repository.saved == {Dataset.INTEGRATED_ALERTS: {IN_APP}}


async def test_the_same_request_twice_gives_the_same_result():
    repository = FakeRepository(set())
    subscriptions = SubscriptionService(repository, FakeEligibility(True))

    await subscriptions.update(TARGET, DATASETS, {EMAIL})
    repository.current = repository.saved[Dataset.INTEGRATED_ALERTS]
    await subscriptions.update(TARGET, DATASETS, {EMAIL})

    assert repository.saved == {Dataset.INTEGRATED_ALERTS: {EMAIL, IN_APP}}
