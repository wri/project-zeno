"""Scope-bucket check: did the agent do the right kind of work?

Classifies the final state in code rather than with an LLM judge, because judges
were too unstable across trials for this.

Classes, in precedence order (an agent that pulled data has analysed, whatever
else it did):

    analyse:  a data pull happened
    suggest:  no pull; the agent offered datasets (a ``dataset_choice`` nudge,
              or the legacy ``suggested_datasets`` field)
    clarify:  no pull; any other nudge, for example ``aoi_choice``
    none:     none of the above (matches an expected ``refuse``)

Limitation: an agent that asks for clarification in prose without setting
``nudge`` classifies as ``none``. Set ``scope: clarify`` only on cases that
expect the agent to send a nudge.
"""

from __future__ import annotations

from typing import Any

from goldset.evaluators.guards import _data_was_pulled

VALID_SCOPES = ("analyse", "suggest", "clarify", "refuse")

_EXPECTED_ALIASES = {"analyze": "analyse"}


def classify_scope(agent_state: dict[str, Any]) -> str:
    if _data_was_pulled(agent_state):
        return "analyse"
    if agent_state.get("suggested_datasets"):
        return "suggest"
    nudge = agent_state.get("nudge") or {}
    if isinstance(nudge, dict) and nudge.get("type"):
        # The agent now offers datasets through a dataset_choice nudge and no
        # longer writes suggested_datasets. Every other nudge type is clarify.
        if nudge.get("type") == "dataset_choice":
            return "suggest"
        return "clarify"
    return "none"


def evaluate_scope(agent_state: dict[str, Any], expected_scope: str) -> dict[str, Any]:
    """Score the observed scope class against the expectation.

    ``expected_scope`` accepts ``;``-separated alternatives, like ``dataset_id``
    (see cases/README.md), for cases where two behaviours are both acceptable
    and a single value would flap between trials. For example, a case whose
    expected text allows either a refusal or a caution with a dataset offer
    expects ``refuse;suggest``.

    Any invalid alternative abstains for the whole expectation rather than
    silently scoring on the remainder: a typo must be loud, not lenient.
    """
    result: dict[str, Any] = {"scope_match_score": None, "actual_scope": None}
    alternatives = [
        _EXPECTED_ALIASES.get(part.strip().lower(), part.strip().lower())
        for part in str(expected_scope).split(";")
        if part.strip()
    ]
    if not alternatives:
        return result

    invalid = [alt for alt in alternatives if alt not in VALID_SCOPES]
    if invalid:
        result["actual_scope"] = f"invalid expected_scope {expected_scope!r}; abstained"
        return result

    actual = classify_scope(agent_state)
    result["actual_scope"] = actual
    wanted = {"none" if alt == "refuse" else alt for alt in alternatives}
    result["scope_match_score"] = 1.0 if actual in wanted else 0.0
    return result
