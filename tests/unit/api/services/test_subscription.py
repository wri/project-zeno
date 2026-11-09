from uuid import uuid4

import pytest

from src.api.services.subscription import (
    Dataset,
    EmailAlertsUnavailableError,
    SubscriptionMode,
    SubscriptionModeRepository,
    SubscriptionService,
    SubscriptionTarget,
)

EMAIL = SubscriptionMode.EMAIL
DATASETS = {Dataset.INTEGRATED_ALERTS}


class FakeRepository(SubscriptionModeRepository):
    def __init__(self):
        self.saved = {}

    async def set_modes(self, target, dataset, modes):
        self.saved[dataset] = modes


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

    with pytest.raises(EmailAlertsUnavailableError):
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
