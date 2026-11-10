"""Tests for tools/report_run.py: the four report layers (verdicts, bucket
table, reconciliation, diagnostics) and the failing-rows list."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from report_run import render

RUN = {
    "run_id": "20260801T000000Z_staging",
    "environment": "staging",
    "build": "GNW test",
    "ff": None,
    "num_trials": 1,
    "caseset_version": "cs1",
    "results": [
        {
            "uid": "u1",
            "id": "1-001",
            "checks": {
                "aoi_id_match": 1.0,
                "agent_answer": 1.0,
                "chart_produced": 1.0,
                "data_pull_exists": 1.0,
                "answered_without_data": 1.0,
            },
        },
        {
            "uid": "u2",
            "id": "1-002",
            "checks": {"aoi_id_match": 1.0, "agent_answer": 0.0},
            "reasons": {"agent_answer": "figure off"},
        },
        {"uid": "u3", "id": "1-003", "checks": {"date_coverage": 1.0}},
        {
            "uid": "u4",
            "id": "1-004",
            "checks": {"aoi_id_match": 1.0},
            "judge_errors": ["agent_answer"],
            "latency_s": 200.0,
            "info": {"slow": True, "threshold_s": 180.0},
        },
    ],
}

EXPECTED_BY_UID = {
    "u1": {"answer": "42 ha", "aoi_ids": "BRA"},
    "u2": {"answer": "7 ha", "aoi_ids": "BRA"},
    "u3": {},
    "u4": {"aoi_ids": "BRA"},
}


def test_report_layers():
    text = render(RUN, EXPECTED_BY_UID)
    # layer 1: verdicts (u3 measured only an info check, so it's uncovered)
    assert "Rows clean: 1/4" in text
    assert "uncovered 1" in text and "1-003" in text
    # layer 2: bucket table (analysis has no dedicated checks)
    assert "| analysis | shared" in text or "dedicated —" in text
    assert "UNMEASURED" not in text.split("| retrieval")[1].split("\n")[0]
    # layer 3: reconciliation itemises u2's missing must-run checks
    assert "MISSING: 1-002 `chart_produced`" in text
    assert "MISSING: 1-002 `data_pull_exists`" in text
    # layer 4: diagnostics
    assert "Errored rows" in text and "1-004" in text
    assert "Slow rows" in text and "200.0s" in text
    # failing rows name the failed check; no status_by_uid passed here, so
    # the fallback reads the same as a result whose uid the store no longer
    # holds (results/README.md's `stale_case`)
    assert "- 1-002 (status: stale_case): agent_answer" in text


def test_failing_row_shows_the_cases_current_status():
    text = render(RUN, EXPECTED_BY_UID, status_by_uid={"u2": "todo"})
    assert "- 1-002 (status: todo): agent_answer" in text


def test_failing_rows_exclude_info_only_checks_even_when_turn_prefixed():
    """report_run's failing-row line must use the same is_info_only rule
    buckets.row_verdict uses. A bare INFO_ONLY membership check misses
    turn-prefixed names like t2.charts_answer_judge, which would otherwise
    show up as if it were a reason the row failed, when it never gates."""
    run = {
        **RUN,
        "results": [
            {
                "uid": "u5",
                "id": "mt-001",
                "checks": {"t1.agent_answer": 0.0, "t2.charts_answer_judge": 0.0},
            },
        ],
    }
    text = render(run, {"u5": {}})
    assert "- mt-001 (status: stale_case): t1.agent_answer" in text
    assert "charts_answer_judge" not in text.split("## Failing rows")[1]


def test_unmeasured_bucket_is_rendered_not_omitted():
    run = {
        **RUN,
        "results": [
            {"uid": "u1", "id": "1-001", "checks": {"aoi_id_match": 1.0}},
        ],
    }
    text = render(run, {"u1": {"aoi_ids": "BRA"}})
    assert "| analysis | — UNMEASURED | 0 |" in text
    assert "| scope | — UNMEASURED | 0 |" in text
