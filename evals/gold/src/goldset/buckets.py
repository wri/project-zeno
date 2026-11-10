"""The five-bucket scoring model.

Buckets answer "which part of the pipeline broke": Retrieval (did the agent
extract the right things from the prompt), Analysis (right computation),
Explanation (prose faithful to the data), Output (artefacts presented
correctly), Scope (right amount of work).

Every check is tagged below: ``DEDICATED`` (it speaks for one bucket),
``SHARED`` (its failure straddles two buckets and cannot be attributed to
either, so the bucket table reports shared checks separately) or
``INFO_ONLY`` (recorded, never part of a verdict). An info-only check that
also has a ``DEDICATED`` tag still counts in that bucket's tallies.

Row verdicts (``row_verdict``), in order of precedence:

- error: the trial errored or a judge call failed. Never counted as a fail.
- uncovered: no gating check produced a score. Never counted as a pass.
- fail: a gating check scored 0.0.
- pass: otherwise.

``summarize_buckets`` always emits all five buckets, so a bucket with no
scored checks shows as unmeasured instead of disappearing.
"""

from __future__ import annotations

import re
from typing import Any

RETRIEVAL = "retrieval"
ANALYSIS = "analysis"
EXPLANATION = "explanation"
OUTPUT = "output"
SCOPE = "scope"
BUCKETS = (RETRIEVAL, ANALYSIS, EXPLANATION, OUTPUT, SCOPE)

# Checks that speak for exactly one bucket (ledger names, no _score suffix).
DEDICATED: dict[str, str] = {
    "aoi_id_match": RETRIEVAL,
    "dataset_id_match": RETRIEVAL,
    "dataset_parameter_match": RETRIEVAL,
    "context_layer_match": RETRIEVAL,
    "date_extraction": RETRIEVAL,
    "data_pull_exists": RETRIEVAL,
    "pull_source_match": RETRIEVAL,
    "answered_without_data": RETRIEVAL,
    "expected_text_match": EXPLANATION,
    "web_fallback": EXPLANATION,
    "chart_produced": OUTPUT,
    "dashboard_aoi_match": OUTPUT,
    "dashboard_widgets_match": OUTPUT,
    "dashboard_widgets_valid": OUTPUT,
    "clarification_requested": SCOPE,
    "suggested_datasets_match": SCOPE,
    "nudge_match": SCOPE,
    "class_value_match": ANALYSIS,
    "chart_integrity": ANALYSIS,
    "answer_traceability": EXPLANATION,
    "chart_well_formed": OUTPUT,
    "chart_type_match": OUTPUT,
    "scope_match": SCOPE,
    # Multi-turn: scored by runner/multiturn.py, not by a registry evaluator.
    "state_delta": RETRIEVAL,
    # Run-time ground truth. Every way it scores 0.0 is a retrieval failure:
    # a readable pull lacking the value, or no pull at all.
    "ground_truth_match": RETRIEVAL,
}

# Checks whose failure straddles two buckets and cannot be attributed.
SHARED: dict[str, tuple[str, str]] = {
    "charts_answer": (ANALYSIS, OUTPUT),
    "agent_answer": (ANALYSIS, EXPLANATION),
    "dashboard_created": (OUTPUT, SCOPE),
    "ground_truth_answer": (ANALYSIS, EXPLANATION),
}

# Recorded for diagnosis, never part of a verdict. Why each check is here, and
# what re-admits it: src/goldset/evaluators/README.md#info-only-checks
# date_coverage: the state field it reads is unreliable (see data_pull_evaluator).
# answer_traceability: its claim extraction gave false positives.
# class_value_match: its expected figures are not all verified yet.
# charts_answer_judge: the judge's view of chart choice, which flaps between trials.
# ground_truth_answer: judged, so info-only until it shows std <= 0.10 over 3 trials.
INFO_ONLY: frozenset[str] = frozenset(
    {
        "date_coverage",
        "answer_traceability",
        "class_value_match",
        "charts_answer_judge",
        "ground_truth_answer",
    }
)


_TURN_PREFIX = re.compile(r"^t\d+\.")


def base_check_name(check: str) -> str:
    """``t2.aoi_id_match`` -> ``aoi_id_match`` (multi-turn entries flatten
    per-turn checks under a turn prefix)."""
    return _TURN_PREFIX.sub("", check)


def is_info_only(check: str) -> bool:
    return base_check_name(check) in INFO_ONLY


def buckets_for(check: str) -> tuple[str, ...]:
    check = base_check_name(check)
    if check in DEDICATED:
        return (DEDICATED[check],)
    return SHARED.get(check, ())


def row_verdict(entry: dict[str, Any]) -> str:
    """pass | fail | error | uncovered, per the rules above."""
    if entry.get("error") or entry.get("judge_errors"):
        return "error"
    evaluated = {
        name: value
        for name, value in entry.get("checks", {}).items()
        if not is_info_only(name) and value is not None
    }
    if not evaluated:
        return "uncovered"
    return "fail" if any(value == 0.0 for value in evaluated.values()) else "pass"


def _tally(entries: list[dict], names: set[str], bucket: str) -> dict:
    passed = evaluated = 0
    for entry in entries:
        for name, value in entry.get("checks", {}).items():
            if (
                base_check_name(name) in names
                and bucket in buckets_for(name)
                and value is not None
            ):
                evaluated += 1
                passed += value == 1.0
    return {"passed": passed, "evaluated": evaluated}


def summarize_buckets(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """The per-run bucket block stored in the ledger and rendered in reports."""
    # Errored entries are errors, not measurements (row_verdict parity): a
    # conversation that died at turn N must not bank its earlier turns'
    # pass/fail counts into bucket tallies or coverage. Verdicts still see
    # every entry, so the error remains visible.
    scored = [entry for entry in entries if not entry.get("error")]
    summary: dict[str, Any] = {}
    for bucket in BUCKETS:
        dedicated = _tally(scored, set(DEDICATED), bucket)
        shared = _tally(scored, set(SHARED), bucket)
        rows_covered = sum(
            1
            for entry in scored
            if any(
                bucket in buckets_for(name) and value is not None
                for name, value in entry.get("checks", {}).items()
            )
        )
        summary[bucket] = {
            "dedicated": dedicated,
            "shared": shared,
            "rows_covered": rows_covered,
        }
    verdicts: dict[str, int] = {"pass": 0, "fail": 0, "error": 0, "uncovered": 0}
    for entry in entries:
        verdicts[row_verdict(entry)] += 1
    summary["rows_total"] = len(entries)
    summary["verdicts"] = verdicts
    return summary


# ---------------------------------------------------------------------------
# Reconciliation: checks the case set implies vs checks that actually ran.


def _tri(value: str | None) -> bool | None:
    text = str(value or "").strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    return None


def _case_expects_data_pull(expected: dict[str, str]) -> bool:
    if _tri(expected.get("clarification")) is True:
        return False
    if expected.get("answer") or expected.get("ground_truth"):
        return True
    return "insight" in (expected.get("dashboard_widgets") or "")


def implied_checks(expected: dict[str, str]) -> set[str]:
    """Checks that MUST evaluate given a case's expectations. Conditional
    checks (charts_answer, web_fallback, pull_source_match, dashboard
    sub-checks, date_coverage) may legitimately abstain and are never
    implied, so every reconciliation miss is a real hole."""
    implied: set[str] = set()
    if expected.get("aoi_ids"):
        implied.add("aoi_id_match")
    if expected.get("dataset_id"):
        implied.add("dataset_id_match")
    if expected.get("dataset_parameters"):
        implied.add("dataset_parameter_match")
    if expected.get("context_layer"):
        implied.add("context_layer_match")
    if expected.get("start_date") and expected.get("end_date"):
        implied.add("date_extraction")
    if expected.get("answer"):
        implied.update({"agent_answer", "chart_produced"})
    if expected.get("ground_truth"):
        # Abstains only when the harness cannot read the agent's pull — a hole
        # reconciliation should surface, not excuse.
        implied.add("ground_truth_match")
    if _case_expects_data_pull(expected):
        implied.update({"data_pull_exists", "answered_without_data"})
    if expected.get("text"):
        implied.add("expected_text_match")
    if _tri(expected.get("clarification")) is not None:
        implied.add("clarification_requested")
    if expected.get("suggested_datasets"):
        implied.add("suggested_datasets_match")
    if expected.get("nudge_type") or expected.get("nudge_options"):
        implied.add("nudge_match")
    if _tri(expected.get("dashboard_created")) is not None:
        implied.add("dashboard_created")
    if expected.get("dashboard_widgets"):
        implied.add("dashboard_widgets_match")
    if expected.get("class_values"):
        implied.add("class_value_match")
    if expected.get("chart_type"):
        implied.add("chart_type_match")
    if expected.get("scope"):
        implied.add("scope_match")
    return implied


def implied_checks_for_case(case: Any) -> set[str]:
    """Implied checks for a store Case, multi-turn cases included.
    Multi-turn cases imply their per-turn checks under ``t<N>.`` prefixes,
    plus ``t<N>.state_delta`` for every turn carrying delta assertions;
    without this they contribute zero implied checks and a conversation
    whose checks all vanished would pass reconciliation silently."""
    if not getattr(case, "is_multiturn", False):
        return implied_checks(case.expected)
    implied: set[str] = set()
    for number, turn in enumerate(case.turns, start=1):
        for check in implied_checks(turn.get("expected") or {}):
            implied.add(f"t{number}.{check}")
        if turn.get("deltas"):
            implied.add(f"t{number}.state_delta")
    return implied


def reconcile(
    entries: list[dict[str, Any]], implied_by_uid: dict[str, Any]
) -> dict[str, Any]:
    """Implied-vs-evaluated ledger line. ``missing`` must be empty or every
    item explained: silent non-measurement is the bug class this catches.
    Values in ``implied_by_uid`` may be a raw expected-dict (legacy) or a
    precomputed set of check names."""
    implied_total = evaluated_of_implied = 0
    missing: list[dict[str, str]] = []
    unmatched_rows = 0
    for entry in entries:
        expected = implied_by_uid.get(entry.get("uid") or "")
        if expected is None:
            unmatched_rows += 1
            continue
        implied = expected if isinstance(expected, set) else implied_checks(expected)
        for check in sorted(implied):
            implied_total += 1
            if entry.get("checks", {}).get(check) is not None:
                evaluated_of_implied += 1
            else:
                missing.append(
                    {"id": entry.get("id", "?"), "uid": entry["uid"], "check": check}
                )
    return {
        "implied": implied_total,
        "evaluated_of_implied": evaluated_of_implied,
        "missing": missing,
        "rows_not_in_store": unmatched_rows,
    }
