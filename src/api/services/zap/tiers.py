"""When is a zap decision clear, and when does a plan need a confirmation.

The rule is in docs/zap-mode-plan.md ("Tiers and confirmation"). All the
thresholds are here, so that the dashboard eval can tune them in one place.

- A jev decision is clear when the probability of the selected option is at
  least JEV_MIN_PROBABILITY, and at least JEV_MIN_MARGIN above the second
  option.
- A Clairic value is clear when `p_null` is below CLAIRIC_P_NULL_LOW or
  above CLAIRIC_P_NULL_HIGH: the model is sure that the request names the
  value, or sure that it does not.

Tiers: 0 is a map change, 1 is a dashboard addition, 2 is a dashboard
addition with a decision that is not clear. A tier 2 plan needs a
confirmation. The map path does not use the confirmation: undo takes a map
change back.
"""

from typing import Iterable, Optional

JEV_MIN_PROBABILITY = 0.7
JEV_MIN_MARGIN = 0.25
CLAIRIC_P_NULL_LOW = 0.2
CLAIRIC_P_NULL_HIGH = 0.8

# The other options that a decision carries for a one-click correction.
TOP_OPTIONS = 3

TIER_MAP = 0
TIER_ADDITION = 1
TIER_CONFIRM = 2


def jev_clear(choice: str, probabilities: dict[str, float]) -> bool:
    """Whether a jev answer is clear. With no probabilities (an old answer
    shape), the decision is not clear."""
    if not probabilities:
        return False
    selected = probabilities.get(choice, 0.0)
    second = max(
        (p for option, p in probabilities.items() if option != choice),
        default=0.0,
    )
    return (
        selected >= JEV_MIN_PROBABILITY and selected - second >= JEV_MIN_MARGIN
    )


def clairic_clear(probability: float) -> bool:
    """Whether a Clairic value is clear. `probability` is the probability
    of the answer, 1 - p_null for a value or p_null for "not named"; the
    rule is the same for both, because it is symmetric."""
    p_null = 1 - probability
    return p_null < CLAIRIC_P_NULL_LOW or p_null > CLAIRIC_P_NULL_HIGH


def dashboard_tier(clear: Iterable[Optional[bool]]) -> int:
    """The tier of a dashboard addition, from the `clear` flags of the
    decisions that the addition depends on. None counts as clear."""
    return (
        TIER_CONFIRM if any(flag is False for flag in clear) else TIER_ADDITION
    )
