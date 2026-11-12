"""When is a zap decision clear, and when does a plan need a confirmation.

The rule is in docs/zap-mode-plan.md ("Tiers and confirmation"). All the
thresholds are here, so that the dashboard eval can tune them in one place.

- A jev decision is clear when the probability of the selected option is at
  least JEV_MIN_PROBABILITY, and at least JEV_MIN_MARGIN above the second
  option.
- A Clairic value is clear when `p_null` is below CLAIRIC_P_NULL_LOW or
  above CLAIRIC_P_NULL_HIGH: the model is sure that the request names the
  value, or sure that it does not.

Tiers: 0 is a map change, 1 is a dashboard addition or layout edit
(`add_section`, `move`, `resize`, `rename`), 2 is a dashboard plan that
needs a confirmation: a decision that is not clear, a removal or a new
period (ALWAYS_CONFIRM), or an edit of more than one widget
(MAX_TIER1_WIDGETS). The map path does not use the confirmation: undo takes a map
change back.
"""

from typing import Iterable, Optional

JEV_MIN_PROBABILITY = 0.7
JEV_MIN_MARGIN = 0.25
CLAIRIC_P_NULL_LOW = 0.2
CLAIRIC_P_NULL_HIGH = 0.8

# The other options that a decision carries for a one-click correction.
TOP_OPTIONS = 3

# The dashboard actions that always need a confirmation: a removal and a
# new period lose what the dashboard shows, and a dashboard has no undo.
ALWAYS_CONFIRM = ("change_period", "remove")
# A plan that changes more widgets than this needs a confirmation.
MAX_TIER1_WIDGETS = 1

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


def dashboard_tier(
    clear: Iterable[Optional[bool]],
    action: Optional[str] = None,
    changed_widgets: int = 0,
) -> int:
    """The tier of a dashboard plan, from the `clear` flags of the
    decisions that the plan depends on (None counts as clear), the action,
    and the number of widgets that exist and that the plan changes."""
    if action in ALWAYS_CONFIRM or changed_widgets > MAX_TIER1_WIDGETS:
        return TIER_CONFIRM
    return (
        TIER_CONFIRM if any(flag is False for flag in clear) else TIER_ADDITION
    )
