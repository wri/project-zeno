"""Multi-turn conversations: same thread, per-turn checks, and state-delta
assertions between turns.

Mechanically cheap because the API is thread-native: each turn is one
``run_test`` call sharing the conversation's ``thread_id``; the state
endpoint returns the full current state after every turn, so every existing
validator applies per-turn unchanged.

Delta assertions compare the *snapshots* two consecutive turns produced:

    changed: [field, ...]   the field must differ from the previous turn
    retain:  [field, ...]   the field must be identical (catches lost context)
    absent:  [field, ...]   the field must be empty (catches a value carried
                            over from the previous turn)

Snapshots are built from the TestResult's ``actual_*`` diagnostics, so the
comparison is over exactly what the validators already read.
"""

from __future__ import annotations

from typing import Any

from goldset.eval_types import TestResult

SNAPSHOT_FIELDS: dict[str, str] = {
    "aoi_ids": "actual_id",
    "dataset_id": "actual_dataset_id",
    "context_layer": "actual_context_layer",
    "start_date": "actual_extracted_start_date",
    "end_date": "actual_extracted_end_date",
    "suggested_datasets": "actual_suggested_datasets",
    "nudge_type": "actual_nudge_type",
    "dashboard_id": "actual_dashboard_id",
}


def state_snapshot(result: TestResult) -> dict[str, str]:
    dumped = result.model_dump()
    return {
        field: str(dumped.get(source) or "")
        for field, source in SNAPSHOT_FIELDS.items()
    }


def evaluate_deltas(
    previous: dict[str, str], current: dict[str, str], deltas: dict[str, list[str]]
) -> dict[str, Any]:
    """One score per turn: every asserted transition must hold."""
    problems: list[str] = []
    for field in deltas.get("changed", []):
        if current.get(field, "") == previous.get(field, ""):
            problems.append(
                f"{field} should have changed but is still {previous.get(field)!r}"
            )
    for field in deltas.get("retain", []):
        if current.get(field, "") != previous.get(field, ""):
            problems.append(
                f"{field} should have been retained: "
                f"{previous.get(field)!r} -> {current.get(field)!r}"
            )
    for field in deltas.get("absent", []):
        if current.get(field, ""):
            problems.append(
                f"{field} should be absent but is {current.get(field)!r} — "
                "carryover contamination"
            )
    unknown = [
        field
        for kind in ("changed", "retain", "absent")
        for field in deltas.get(kind, [])
        if field not in SNAPSHOT_FIELDS
    ]
    if unknown:
        return {
            "state_delta_score": None,
            "state_delta_reason": f"unknown snapshot fields {unknown}; abstained",
        }
    return {
        "state_delta_score": 0.0 if problems else 1.0,
        "state_delta_reason": "; ".join(problems) or None,
    }


async def run_conversation(runner, case, result_to_entry, artifact_sink_factory=None):
    """Drive one scripted conversation and build its ledger entry.

    ``runner`` is an APITestRunner; ``result_to_entry`` is the CLI's
    TestResult->entry mapper (injected to avoid a circular import);
    ``artifact_sink_factory(turn_number)`` returns a per-turn sink or None.

    A turn that errors (``run_test`` sets ``result.error`` on a transport
    failure or timeout) aborts the conversation:
    firing turn N+1 would race a possibly-still-processing backend and
    compare deltas against an all-empty snapshot. The un-run turns
    contribute no checks at all; the entry records the turn-tagged error.
    """
    from uuid import uuid4

    from goldset.adapter import turn_to_expected

    thread_id = str(uuid4())
    turn_entries: list[dict[str, Any]] = []
    previous_snapshot: dict[str, str] | None = None
    for number, turn in enumerate(case.turns, start=1):
        sink = artifact_sink_factory(number) if artifact_sink_factory else None
        result = await runner.run_test(
            turn["query"],
            turn_to_expected(case, turn),
            artifact_sink=sink,
            thread_id=thread_id,
        )
        turn_entry = result_to_entry(result, case.uid)
        if turn_entry.get("error"):
            turn_entries.append(turn_entry)
            break
        # Delta computation must never take down the whole run (run_cases
        # gathers without return_exceptions): degrade this turn to an error
        # state instead, mirroring run_test's own try/except degradation.
        try:
            snapshot = state_snapshot(result)
            deltas = turn.get("deltas") or {}
            if deltas and previous_snapshot is not None:
                delta_result = evaluate_deltas(previous_snapshot, snapshot, deltas)
                turn_entry["checks"]["state_delta"] = delta_result["state_delta_score"]
                if delta_result["state_delta_reason"]:
                    turn_entry.setdefault("reasons", {})["state_delta"] = delta_result[
                        "state_delta_reason"
                    ]
        except Exception as delta_error:
            turn_entry["error"] = f"delta evaluation failed: {delta_error}"
            turn_entries.append(turn_entry)
            break
        previous_snapshot = snapshot
        turn_entries.append(turn_entry)

    flat_actuals = {
        f"t{number}.{check}": value
        for number, turn_entry in enumerate(turn_entries, start=1)
        for check, value in (turn_entry.get("actuals") or {}).items()
    }
    entry: dict[str, Any] = {
        "uid": case.uid,
        "id": case.id,
        "checks": flatten_turn_checks(turn_entries),
        **({"actuals": flat_actuals} if flat_actuals else {}),
        "turns_detail": [
            {
                "query": turn["query"],
                "reasons": e.get("reasons"),
                "latency_s": e.get("latency_s"),
                "trace_url": e.get("trace_url"),
            }
            for turn, e in zip(case.turns, turn_entries)
        ],
    }
    judge_errors = [
        f"t{n}.{check}"
        for n, e in enumerate(turn_entries, start=1)
        for check in e.get("judge_errors", [])
    ]
    if judge_errors:
        entry["judge_errors"] = judge_errors
    errors = [
        f"t{n}: {e['error']}"
        for n, e in enumerate(turn_entries, start=1)
        if e.get("error")
    ]
    if errors:
        entry["error"] = "; ".join(errors)[:500]
    latencies = [e.get("latency_s") for e in turn_entries if e.get("latency_s")]
    if latencies:
        entry["latency_s"] = round(sum(latencies), 1)
    return entry


def flatten_turn_checks(turn_entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-turn ledger checks -> one flat mapping (``t2.aoi_id_match``), so
    the verdict, bucket, and diff machinery work on conversations without
    special cases."""
    flat: dict[str, Any] = {}
    for number, entry in enumerate(turn_entries, start=1):
        for check, value in entry.get("checks", {}).items():
            flat[f"t{number}.{check}"] = value
    return flat
