"""Convert a store ``Case`` into the ``ExpectedData`` the evaluators read.

Case YAML stores expectation keys without the ``expected_`` prefix.
``ExpectedData`` wants the prefix and does its own parsing (semicolon lists,
tri-state booleans), so this module only adds the prefix: one parser, not two.

The case uid rides along as a pydantic extra field, but nothing relies on it:
the ledger takes its uid from the stored case (``run_cases`` in ``cli.py``),
because a templated query resolves to different text, and so to a different
uid, at run time.

Ground truth enters here too, and this is the only place it does. A case's
``ground_truth`` selector is re-prefixed to ``expected_ground_truth`` by the
loop below, like any other expectation. The values fetched for it at run
start are not from the case, so they are attached separately and unprefixed.
``ground_truth`` defaults to ``None``, so a case without one is built from its
expectations alone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from goldset.eval_types import ExpectedData
from goldset.store import Case

if TYPE_CHECKING:
    from goldset.groundtruth import GroundTruth


def _to_expected(
    case: Case,
    expected: dict[str, str],
    ground_truth: GroundTruth | None = None,
) -> ExpectedData:
    payload = {f"expected_{key}": value for key, value in expected.items()}
    if ground_truth is not None:
        payload["ground_truth_values"] = list(ground_truth.values)
        # "" rather than None so the field keeps its declared str type; an
        # unresolved selector becomes a row error when the check is built.
        payload["ground_truth_unresolved"] = ground_truth.unresolved or ""
    return ExpectedData(
        test_id=case.id,
        test_group=case.group or "unknown",
        status=case.status,
        uid=case.uid,
        **payload,
    )


def case_to_expected(
    case: Case, ground_truth: GroundTruth | None = None
) -> ExpectedData:
    return _to_expected(case, case.expected, ground_truth)


def turn_to_expected(
    case: Case, turn: dict, ground_truth: GroundTruth | None = None
) -> ExpectedData:
    """One turn of a multi-turn case, same prefixing rules.

    Takes ``ground_truth`` for signature parity with ``case_to_expected``; no
    multi-turn case carries a ``ground_truth`` selector today, so it is always
    ``None`` in practice.
    """
    return _to_expected(case, turn.get("expected") or {}, ground_truth)
