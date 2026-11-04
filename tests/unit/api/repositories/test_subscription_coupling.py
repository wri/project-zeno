import pytest

from src.api.repositories.subscription_repository import coupled_modes
from src.api.services.subscription import SubscriptionMode

EMAIL = SubscriptionMode.EMAIL
IN_APP = SubscriptionMode.IN_APP


@pytest.mark.parametrize(
    "current, desired, stored",
    [
        # Email on turns in-app on.
        (set(), {EMAIL}, {EMAIL, IN_APP}),
        ({IN_APP}, {EMAIL, IN_APP}, {EMAIL, IN_APP}),
        # Asking for email on and in-app off at once: email on wins.
        ({IN_APP}, {EMAIL}, {EMAIL, IN_APP}),
        # In-app off turns email off.
        ({EMAIL, IN_APP}, {EMAIL}, set()),
        ({EMAIL, IN_APP}, set(), set()),
        # Email off leaves in-app alone.
        ({EMAIL, IN_APP}, {IN_APP}, {IN_APP}),
        # In-app on and off by itself.
        (set(), {IN_APP}, {IN_APP}),
        ({IN_APP}, set(), set()),
        # The value it already has.
        ({EMAIL, IN_APP}, {EMAIL, IN_APP}, {EMAIL, IN_APP}),
        (set(), set(), set()),
    ],
)
def test_coupled_modes(current, desired, stored):
    assert coupled_modes(current, desired) == stored
