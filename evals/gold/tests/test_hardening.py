"""Regression tests for assorted harness and tooling bugs, one group per bug.

Each test reproduces the original defect:

- Merging trials keeps the errors and judge errors of any trial
  (`test_h3_*`).
- Multi-turn cases contribute their implied checks, prefixed `t<N>.`, to
  reconciliation (`test_h4_*`).
- Reports show per-turn detail for failing conversations (`test_h5_*`).
- Artefact pruning keeps the newest N runs (`test_h6_*`).
- `dataset_id` expectations accept `;`-separated alternatives (`test_h7_*`).

The h numbers are local to this file: test_harness_fixes_ha.py and
test_harness_fixes_hb.py reuse them for unrelated fixes.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from report_run import render as render_report

from goldset.buckets import implied_checks_for_case, reconcile
from goldset.cli import merge_trials, prune_artifacts
from goldset.evaluators.dataset_evaluator import evaluate_dataset_selection
from goldset.store import Case

CASE = Case(
    id="1-002",
    status="done",
    group="direct",
    query="Sao Paulo disturbance in H2 2024?",
    expected={"dataset_id": "11", "answer": "1,319,600 hectares"},
)


# --- errors from any trial survive the merge


def test_h3_merge_trials_unions_errors():
    trials = [
        {
            "uid": "u",
            "id": "x",
            "checks": {"aoi_id_match": 1.0},
            "judge_errors": ["agent_answer"],
            "error": "trial 1 blew up",
        },
        {"uid": "u", "id": "x", "checks": {"aoi_id_match": 1.0}},
        {"uid": "u", "id": "x", "checks": {"aoi_id_match": 1.0}},
    ]
    merged = merge_trials(trials)
    assert merged["judge_errors"] == ["agent_answer"]  # was dropped before
    assert "trial 1 blew up" in merged["error"]


# --- multi-turn cases contribute implied checks

MT = Case(
    id="mt-x",
    status="ready",
    group="multiturn",
    turns=(
        {"query": "q1", "expected": {"clarification": "TRUE"}},
        {
            "query": "q2",
            "expected": {"aoi_ids": "IDN"},
            "deltas": {"changed": ["aoi_ids"]},
        },
    ),
)


def test_h4_multiturn_implied_checks():
    implied = implied_checks_for_case(MT)
    assert implied == {
        "t1.clarification_requested",
        "t2.aoi_id_match",
        "t2.state_delta",
    }
    # single-turn path unchanged
    assert "dataset_id_match" in implied_checks_for_case(CASE)


def test_h4_reconcile_accepts_precomputed_sets():
    entries = [
        {
            "uid": "u1",
            "id": "mt-x",
            "checks": {
                "t1.clarification_requested": 1.0,
                "t2.aoi_id_match": None,
                "t2.state_delta": 1.0,
            },
        }
    ]
    report = reconcile(entries, {"u1": implied_checks_for_case(MT)})
    assert report["implied"] == 3
    assert report["evaluated_of_implied"] == 2
    assert report["missing"] == [
        {"id": "mt-x", "uid": "u1", "check": "t2.aoi_id_match"}
    ]


# --- failing conversations render per-turn detail


def test_h5_report_renders_turn_detail():
    run = {
        "run_id": "20260801T000000Z_staging",
        "environment": "staging",
        "build": "b",
        "ff": None,
        "num_trials": 1,
        "caseset_version": "cs",
        "results": [
            {
                "uid": "u1",
                "id": "mt-x",
                "checks": {"t1.aoi_id_match": 1.0, "t2.state_delta": 0.0},
                "turns_detail": [{"query": "q1"}, {"query": "And for Indonesia?"}],
            }
        ],
    }
    text = render_report(run, {"u1": implied_checks_for_case(MT)})
    assert '- t2 "And for Indonesia?" -> state_delta' in text


# --- artefact pruning keeps the newest N


def test_h6_prune_artifacts(tmp_path, capsys):
    artifacts = tmp_path / "artifacts"
    for run_id in ("20260701T000000Z_a", "20260715T000000Z_b", "20260801T000000Z_c"):
        (artifacts / run_id).mkdir(parents=True)
        (artifacts / run_id / "x.json.gz").write_bytes(b"data")
    assert prune_artifacts(tmp_path, keep_runs=2) == 0
    remaining = sorted(d.name for d in artifacts.iterdir())
    assert remaining == ["20260715T000000Z_b", "20260801T000000Z_c"]


# --- dataset_id accepts ;-separated alternatives


def _state(dataset_id):
    return {
        "dataset": {
            "dataset_id": dataset_id,
            "dataset_name": "x",
            "parameters": [],
            "context_layer": None,
        }
    }


def test_h7_dataset_alternatives_match_any():
    for actual in ("0", "11"):
        result = evaluate_dataset_selection(_state(actual), "0;11", "", "")
        assert result["dataset_id_match_score"] == 1.0, actual
    assert (
        evaluate_dataset_selection(_state("4"), "0;11", "", "")[
            "dataset_id_match_score"
        ]
        == 0.0
    )
    # single-value expectations behave exactly as before
    assert (
        evaluate_dataset_selection(_state("4"), "4", "", "")["dataset_id_match_score"]
        == 1.0
    )
