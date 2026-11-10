"""Regression-diff semantics over synthetic run pairs."""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from diff_runs import classify, diff

TOOL = Path(__file__).resolve().parents[1] / "tools" / "diff_runs.py"


def run_fixture(results, caseset="cs1", run_id="20260731T000000Z_staging"):
    return {
        "run_id": run_id,
        "started": "2026-07-31T00:00:00Z",
        "environment": "staging",
        "build": "GNW test",
        "ff": None,
        "harness": {"repo": "gnw-evals", "sha": "x"},
        "judge_model": "claude-haiku-4-5",
        "num_trials": 1,
        "caseset_version": caseset,
        "results": results,
    }


def run_tool(tmp_path, run_a, run_b, *flags):
    """Invoke tools/diff_runs.py as CI would, on two serialised runs."""
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps(run_a))
    b.write_text(json.dumps(run_b))
    return subprocess.run(
        [sys.executable, str(TOOL), str(a), str(b), *flags],
        capture_output=True,
        text=True,
    )


RUN_A = run_fixture(
    [
        {
            "uid": "u1",
            "id": "1-001",
            "checks": {"aoi_id_match": 1.0, "agent_answer": 1.0},
        },
        {
            "uid": "u2",
            "id": "1-002",
            "checks": {"aoi_id_match": 0.0, "charts_answer": None},
        },
        {"uid": "u3", "id": "1-003", "checks": {"aoi_id_match": 1.0}},
        {
            "uid": None,
            "id": "1-009",
            "stale_case": True,
            "checks": {"aoi_id_match": 1.0},
        },
    ]
)
RUN_B = run_fixture(
    [
        {
            "uid": "u1",
            "id": "1-001",
            "checks": {"aoi_id_match": 1.0, "agent_answer": 0.0},
            "reasons": {"agent_answer": "figure off by 12%"},
        },
        {
            "uid": "u2",
            "id": "1-002",
            "checks": {"aoi_id_match": 1.0, "charts_answer": 1.0},
        },
        {"uid": "u4", "id": "1-004", "checks": {"aoi_id_match": 1.0}},
    ],
    run_id="20260731T010000Z_staging",
)


def test_classify_covers_all_transitions():
    assert classify(1.0, 0.0) == "regressions"
    assert classify(0.0, 1.0) == "recoveries"
    assert classify(None, 1.0) == "coverage_gained"
    assert classify(None, 0.0) == "coverage_gained"
    assert classify(1.0, None) == "coverage_lost"
    assert classify(1.0, 1.0) is None
    assert classify(None, None) is None


def test_diff_over_intersection_only():
    report = diff(RUN_A, RUN_B)
    assert report["shared_cases"] == 2  # u1, u2 (u3/u4 are churn, stale excluded)
    assert report["only_in_a"] == 1 and report["only_in_b"] == 1
    assert report["stale_a"] == 1 and report["stale_b"] == 0

    assert [r["check"] for r in report["regressions"]] == ["agent_answer"]
    assert report["regressions"][0]["reason"] == "figure off by 12%"
    assert [r["check"] for r in report["recoveries"]] == ["aoi_id_match"]
    assert [r["check"] for r in report["coverage_gained"]] == ["charts_answer"]
    assert report["coverage_lost"] == []


def test_stale_rows_never_counted_as_regression():
    # the stale 1-009 in RUN_A passes aoi; absent in RUN_B: must not appear
    report = diff(RUN_A, RUN_B)
    ids = [r["id"] for kind in ("regressions", "recoveries") for r in report[kind]]
    assert "1-009" not in ids


def test_strict_refuses_cross_caseset_comparison(tmp_path):
    run_b_cs2 = run_fixture(
        RUN_B["results"], caseset="cs2", run_id="20260731T010000Z_staging"
    )
    strict = run_tool(tmp_path, RUN_A, run_b_cs2, "--strict")
    assert strict.returncode == 2
    loose = run_tool(tmp_path, RUN_A, run_b_cs2)
    assert loose.returncode == 0
    assert "comparing uid intersection only" in loose.stdout


# ---------------------------------------------------------------------------
# Release gate: INFO_ONLY exclusion, regressions_by_bucket, coverage loss.

GATE_A = run_fixture(
    [
        {
            "uid": "u1",
            "id": "1-001",
            "checks": {"aoi_id_match": 1.0, "agent_answer": 1.0, "date_coverage": 1.0},
        },
    ]
)
# date_coverage (info-only) regresses alongside two real checks: one
# dedicated (aoi_id_match -> retrieval), one shared (agent_answer ->
# analysis + explanation).
GATE_B_REAL_AND_INFO = run_fixture(
    [
        {
            "uid": "u1",
            "id": "1-001",
            "checks": {"aoi_id_match": 0.0, "agent_answer": 0.0, "date_coverage": 0.0},
        },
    ],
    run_id="20260731T010000Z_staging",
)
# ONLY date_coverage regresses; the real checks hold.
GATE_B_INFO_ONLY = run_fixture(
    [
        {
            "uid": "u1",
            "id": "1-001",
            "checks": {"aoi_id_match": 1.0, "agent_answer": 1.0, "date_coverage": 0.0},
        },
    ],
    run_id="20260731T010000Z_staging",
)
# A real check silently stops being evaluated (1.0 -> None).
COV_B_REAL_LOST = run_fixture(
    [
        {
            "uid": "u1",
            "id": "1-001",
            "checks": {"aoi_id_match": None, "agent_answer": 1.0, "date_coverage": 1.0},
        },
    ],
    run_id="20260731T010000Z_staging",
)
# Only the info-only check stops being evaluated.
COV_B_INFO_LOST = run_fixture(
    [
        {
            "uid": "u1",
            "id": "1-001",
            "checks": {"aoi_id_match": 1.0, "agent_answer": 1.0, "date_coverage": None},
        },
    ],
    run_id="20260731T010000Z_staging",
)


def test_gate_fails_on_real_regression_despite_info_only_noise(tmp_path):
    result = run_tool(tmp_path, GATE_A, GATE_B_REAL_AND_INFO, "--fail-on-regression")
    assert result.returncode == 1

    report = diff(GATE_A, GATE_B_REAL_AND_INFO)
    assert sorted(r["check"] for r in report["regressions"]) == [
        "agent_answer",
        "aoi_id_match",
        "date_coverage",
    ]
    # info-only regressions never enter the bucket counts
    assert report["regressions_by_bucket"] == {
        "retrieval": 1,
        "analysis": 1,
        "explanation": 1,
        "output": 0,
        "scope": 0,
    }


def test_gate_passes_when_only_info_only_regresses(tmp_path):
    result = run_tool(tmp_path, GATE_A, GATE_B_INFO_ONLY, "--fail-on-regression")
    assert result.returncode == 0

    report = diff(GATE_A, GATE_B_INFO_ONLY)
    assert [r["check"] for r in report["regressions"]] == ["date_coverage"]
    assert report["regressions"][0]["info_only"] is True
    assert report["regressions_by_bucket"] == {
        "retrieval": 0,
        "analysis": 0,
        "explanation": 0,
        "output": 0,
        "scope": 0,
    }


def test_fail_on_coverage_loss_gates_real_check(tmp_path):
    result = run_tool(tmp_path, GATE_A, COV_B_REAL_LOST, "--fail-on-coverage-loss")
    assert result.returncode == 1

    report = diff(GATE_A, COV_B_REAL_LOST)
    assert [c["check"] for c in report["coverage_lost"]] == ["aoi_id_match"]
    assert report["coverage_lost"][0]["info_only"] is False


def test_coverage_loss_passes_without_flag(tmp_path):
    # off by default: without the flag, coverage loss does not fail the diff
    result = run_tool(tmp_path, GATE_A, COV_B_REAL_LOST)
    assert result.returncode == 0
    gated = run_tool(tmp_path, GATE_A, COV_B_REAL_LOST, "--fail-on-regression")
    assert gated.returncode == 0  # coverage loss is not a regression


def test_fail_on_coverage_loss_ignores_info_only(tmp_path):
    result = run_tool(tmp_path, GATE_A, COV_B_INFO_LOST, "--fail-on-coverage-loss")
    assert result.returncode == 0

    report = diff(GATE_A, COV_B_INFO_LOST)
    assert [c["check"] for c in report["coverage_lost"]] == ["date_coverage"]
    assert report["coverage_lost"][0]["info_only"] is True


# ---------------------------------------------------------------------------
# Multi-turn entries flatten per-turn checks under a ``t<N>.`` prefix; the
# info-only rule must see through it, as buckets.row_verdict does.

MT_A = run_fixture(
    [
        {
            "uid": "m1",
            "id": "mt-001",
            "checks": {
                "t1.date_coverage": 1.0,
                "t1.aoi_id_match": 1.0,
                "t2.charts_answer_judge": 1.0,
                "t2.answer_traceability": 1.0,
            },
        },
    ]
)
# Every prefixed info-only check flips (two regress, one stops being
# evaluated); the one gating check holds.
MT_B_INFO_ONLY = run_fixture(
    [
        {
            "uid": "m1",
            "id": "mt-001",
            "checks": {
                "t1.date_coverage": 0.0,
                "t1.aoi_id_match": 1.0,
                "t2.charts_answer_judge": 0.0,
                "t2.answer_traceability": None,
            },
        },
    ],
    run_id="20260731T010000Z_staging",
)


def test_turn_prefixed_info_only_checks_never_gate(tmp_path):
    result = run_tool(
        tmp_path,
        MT_A,
        MT_B_INFO_ONLY,
        "--fail-on-regression",
        "--fail-on-coverage-loss",
    )
    assert result.returncode == 0, result.stdout

    report = diff(MT_A, MT_B_INFO_ONLY)
    assert sorted(r["check"] for r in report["regressions"]) == [
        "t1.date_coverage",
        "t2.charts_answer_judge",
    ]
    assert all(r["info_only"] for r in report["regressions"])
    assert [c["check"] for c in report["coverage_lost"]] == ["t2.answer_traceability"]
    assert report["coverage_lost"][0]["info_only"] is True


def test_turn_prefixed_gating_check_still_gates(tmp_path):
    mt_b_real = run_fixture(
        [
            {
                "uid": "m1",
                "id": "mt-001",
                "checks": {**MT_A["results"][0]["checks"], "t1.aoi_id_match": 0.0},
            },
        ],
        run_id="20260731T010000Z_staging",
    )
    result = run_tool(tmp_path, MT_A, mt_b_real, "--fail-on-regression")
    assert result.returncode == 1

    report = diff(MT_A, mt_b_real)
    assert [r["check"] for r in report["regressions"]] == ["t1.aoi_id_match"]
    assert report["regressions"][0]["info_only"] is False
    assert report["regressions_by_bucket"]["retrieval"] == 1


# ---------------------------------------------------------------------------
# The headline must say how many transitions the gate acts on, not just the
# total; the JSON keeps its shape and gains the gating counts.


def test_headline_splits_gating_from_info_only(tmp_path):
    result = run_tool(tmp_path, GATE_A, GATE_B_REAL_AND_INFO)
    assert "**3 regressions (2 gating, 1 info-only), 0 recoveries" in result.stdout
    assert "0 checks lost (0 gating, 0 info-only)**" in result.stdout

    lost = run_tool(tmp_path, MT_A, MT_B_INFO_ONLY)
    assert "**2 regressions (0 gating, 2 info-only)" in lost.stdout
    assert "1 checks lost (0 gating, 1 info-only)**" in lost.stdout


def test_json_report_keeps_its_keys_and_adds_gating_counts(tmp_path):
    out = tmp_path / "report.json"
    result = run_tool(tmp_path, GATE_A, GATE_B_REAL_AND_INFO, "--json", str(out))
    assert result.returncode == 0
    report = json.loads(out.read_text())
    for key in (
        "regressions",
        "recoveries",
        "coverage_gained",
        "coverage_lost",
        "regressions_by_bucket",
        "shared_cases",
        "only_in_a",
        "only_in_b",
        "stale_a",
        "stale_b",
    ):
        assert key in report
    assert len(report["regressions"]) == 3
    assert report["gating_regressions"] == 2
    assert report["gating_coverage_lost"] == 0

    info_lost = diff(GATE_A, COV_B_INFO_LOST)
    assert info_lost["gating_coverage_lost"] == 0
    real_lost = diff(GATE_A, COV_B_REAL_LOST)
    assert real_lost["gating_coverage_lost"] == 1


def test_help_keeps_the_docstring_layout():
    # The transition table is only readable with its line breaks intact.
    result = subprocess.run(
        [sys.executable, str(TOOL), "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "\n    regression        1.0 -> 0.0\n" in result.stdout


# ---------------------------------------------------------------------------
# Data bumps: a ground-truth check that flips because the fetched data changed.

GT_REQUEST = {
    "endpoint": "/v0/land_change/tree_cover_loss/analytics",
    "payload": {"aoi": {"type": "admin", "ids": ["MDG.3.4"]}},
}
RUN_B_ID = "20260731T010000Z_staging"


def gt_entry(
    match,
    digest,
    values,
    agent_values=None,
    *,
    request=GT_REQUEST,
    fixed=False,
    checks=None,
    trials=None,
):
    ground_truth = {
        "selector": "sum(area_ha)",
        "values": values,
        "digest": digest,
        "dataset_id": "4",
        "content_date_fixed": fixed,
        "request": request,
    }
    if agent_values is not None:
        ground_truth["agent_values"] = agent_values
    entry = {
        "uid": "g1",
        "id": "1-046",
        "ground_truth": ground_truth,
        "checks": {"ground_truth_match": match, **(checks or {})},
    }
    if trials is not None:
        entry["trials"] = [{"checks": {"ground_truth_match": t}} for t in trials]
    return entry


def gt_run(entry, run_id="20260731T000000Z_staging"):
    run = run_fixture([entry], run_id=run_id)
    run["ground_truth"] = {
        "base_url": "https://analytics.example",
        "cases": 1,
        "prefetch_seconds": 1.0,
        "tolerance": 0.02,
    }
    return run


def test_flip_with_a_moved_digest_is_a_data_bump_not_a_regression(tmp_path):
    """The agent still reads the previous figure: the flip is the data's doing."""
    run_a = gt_run(gt_entry(1.0, "aaaa1111", [100.0], [[100.0]]))
    run_b = gt_run(gt_entry(0.0, "bbbb2222", [110.0], [[100.0]]), run_id=RUN_B_ID)
    report = diff(run_a, run_b)
    assert report["regressions"] == []
    [bump] = report["data_bumps"]
    assert (bump["check"], bump["cause"], bump["direction"]) == (
        "ground_truth_match",
        "data",
        "1.0 → 0.0",
    )
    assert bump["digests"] == ["aaaa1111", "bbbb2222"]
    assert "possible_hidden_regression" not in bump

    result = run_tool(tmp_path, run_a, run_b, "--fail-on-regression")
    assert result.returncode == 0
    assert "1 data bumps" in result.stdout


def test_a_flip_with_the_same_digest_is_still_a_regression(tmp_path):
    """The headline stays honest: identical numbers in both runs means the agent moved."""
    run_a = gt_run(gt_entry(1.0, "aaaa1111", [100.0], [[100.0]]))
    run_b = gt_run(gt_entry(0.0, "aaaa1111", [100.0], [[12.0]]), run_id=RUN_B_ID)
    report = diff(run_a, run_b)
    assert [r["check"] for r in report["regressions"]] == ["ground_truth_match"]
    assert report["data_bumps"] == []
    assert run_tool(tmp_path, run_a, run_b, "--fail-on-regression").returncode == 1


def test_a_recovery_with_a_moved_digest_is_a_data_bump():
    """A data change can't count in the agent's favour either."""
    run_a = gt_run(gt_entry(0.0, "aaaa1111", [100.0], [[90.0]]))
    run_b = gt_run(gt_entry(1.0, "bbbb2222", [90.0], [[90.0]]), run_id=RUN_B_ID)
    report = diff(run_a, run_b)
    assert report["recoveries"] == []
    assert [b["direction"] for b in report["data_bumps"]] == ["0.0 → 1.0"]


def test_the_cause_names_a_request_change_and_a_fixed_dataset():
    run_a = gt_run(gt_entry(1.0, "aaaa1111", [100.0]))
    changed = {**GT_REQUEST, "payload": {"aoi": {"type": "admin", "ids": ["MDG.3"]}}}
    request_b = gt_run(
        gt_entry(0.0, "bbbb2222", [110.0], request=changed), run_id=RUN_B_ID
    )
    assert diff(run_a, request_b)["data_bumps"][0]["cause"] == "request"
    fixed_b = gt_run(gt_entry(0.0, "bbbb2222", [110.0], fixed=True), run_id=RUN_B_ID)
    assert diff(run_a, fixed_b)["data_bumps"][0]["cause"] == "fixed_dataset"


def test_other_checks_on_a_bumped_row_still_regress():
    """A data change explains ground-truth flips only."""
    run_a = gt_run(gt_entry(1.0, "aaaa1111", [100.0], checks={"aoi_id_match": 1.0}))
    run_b = gt_run(
        gt_entry(0.0, "bbbb2222", [110.0], checks={"aoi_id_match": 0.0}),
        run_id=RUN_B_ID,
    )
    report = diff(run_a, run_b)
    assert [r["check"] for r in report["regressions"]] == ["aoi_id_match"]
    assert [b["check"] for b in report["data_bumps"]] == ["ground_truth_match"]


def test_a_missing_digest_leaves_the_regression_counted():
    entry_a = gt_entry(1.0, "aaaa1111", [100.0])
    del entry_a["ground_truth"]["digest"]
    run_b = gt_run(gt_entry(0.0, "bbbb2222", [110.0]), run_id=RUN_B_ID)
    report = diff(gt_run(entry_a), run_b)
    assert [r["check"] for r in report["regressions"]] == ["ground_truth_match"]
    assert report["data_bumps"] == []


# --- the blind spot: a real break landing in the same run as a data change


def test_a_bump_is_flagged_when_the_agent_figure_matches_neither_run(tmp_path):
    run_a = gt_run(gt_entry(1.0, "aaaa1111", [100.0], [[100.0]]))
    run_b = gt_run(gt_entry(0.0, "bbbb2222", [110.0], [[12.0]]), run_id=RUN_B_ID)
    [bump] = diff(run_a, run_b)["data_bumps"]
    assert "matching neither run's data" in bump["possible_hidden_regression"]

    # detected and reported, never gated
    result = run_tool(tmp_path, run_a, run_b, "--fail-on-regression")
    assert result.returncode == 0
    assert "possible hidden regression" in result.stdout


def test_a_bump_is_flagged_when_the_agent_pull_lacked_the_metric():
    run_a = gt_run(gt_entry(1.0, "aaaa1111", [100.0], [[100.0]]))
    run_b = gt_run(gt_entry(0.0, "bbbb2222", [110.0], [[None]]), run_id=RUN_B_ID)
    [bump] = diff(run_a, run_b)["data_bumps"]
    assert bump["possible_hidden_regression"] == (
        "the agent's pull held no figure for the metric"
    )


def test_only_the_failing_trials_are_examined():
    run_a = gt_run(gt_entry(1.0, "aaaa1111", [100.0], [[100.0]] * 3, trials=[1.0] * 3))
    # trial 1 passed on the chart fallback, so it carries no figure: not evidence
    stale = gt_entry(
        0.0, "bbbb2222", [110.0], [[None], [100.0], [100.0]], trials=[1.0, 0.0, 0.0]
    )
    [bump] = diff(run_a, gt_run(stale, run_id=RUN_B_ID))["data_bumps"]
    assert "possible_hidden_regression" not in bump

    broken = gt_entry(
        0.0, "bbbb2222", [110.0], [[None], [100.0], [12.0]], trials=[1.0, 0.0, 0.0]
    )
    [bump] = diff(run_a, gt_run(broken, run_id=RUN_B_ID))["data_bumps"]
    assert "possible_hidden_regression" in bump


def test_bumps_without_recorded_agent_figures_are_not_flagged():
    run_a = gt_run(gt_entry(1.0, "aaaa1111", [100.0]))
    run_b = gt_run(gt_entry(0.0, "bbbb2222", [110.0]), run_id=RUN_B_ID)
    assert "possible_hidden_regression" not in diff(run_a, run_b)["data_bumps"][0]


def test_a_synthetic_data_release_is_classified_end_to_end():
    """Two tables served for the same request, through the real prefetch and
    ledger record: the digest moves, the request doesn't, and the flip is a
    data bump rather than a regression."""
    import httpx

    from goldset.groundtruth.client import AnalyticsClient
    from goldset.groundtruth.fetch import prefetch
    from goldset.store import Case

    case = Case(
        id="1-076",
        status="done",
        group="direct",
        query="q",
        expected={
            "aoi_ids": "RUS",
            "aoi_source": "gadm",
            "dataset_id": "4",
            "ground_truth": "sum(area_ha)",
        },
    )

    def serving(table):
        def handler(request):
            if request.method == "POST":
                return httpx.Response(
                    200, json={"status": "saved", "data": {"link": "http://a/x/r"}}
                )
            return httpx.Response(200, json={"data": {"result": table}})

        return AnalyticsClient(token="t", transport=httpx.MockTransport(handler))

    before = {"tree_cover_loss_year": [2024, 2025], "area_ha": [300.0, 400.0]}
    after = {
        "tree_cover_loss_year": [2024, 2025, 2026],
        "area_ha": [300.0, 400.0, 500.0],
    }
    record_a = prefetch([case], serving(before))[case.uid].to_ledger()
    record_b = prefetch([case], serving(after))[case.uid].to_ledger()
    assert record_a["digest"] != record_b["digest"]
    assert record_a["request"] == record_b["request"]

    def entry(score, record, figure):
        return {
            "uid": case.uid,
            "id": case.id,
            "checks": {"ground_truth_match": score},
            "ground_truth": {**record, "agent_values": [[figure]]},
        }

    # the agent still sums the two years it saw before: a stale read, not a break
    report = diff(
        gt_run(entry(1.0, record_a, 700.0)),
        gt_run(entry(0.0, record_b, 700.0), run_id=RUN_B_ID),
    )
    assert report["regressions"] == []
    [bump] = report["data_bumps"]
    assert bump["cause"] == "data"
    assert "possible_hidden_regression" not in bump
