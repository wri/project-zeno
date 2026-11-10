"""Tests for goldset.buckets: how checks map to the five buckets, row
verdicts, bucket tallies and implied-check reconciliation."""

from goldset.buckets import (
    BUCKETS,
    DEDICATED,
    INFO_ONLY,
    SHARED,
    buckets_for,
    implied_checks,
    reconcile,
    row_verdict,
    summarize_buckets,
)
from goldset.registry import ALL_SCORE_FIELDS


def test_every_registered_check_is_tagged_exactly_once():
    tagged = set(DEDICATED) | set(SHARED) | set(INFO_ONLY)
    registered = {field.removesuffix("_score") for field in ALL_SCORE_FIELDS}
    # state_delta is produced by the multiturn orchestration, not a
    # registry evaluator, so it is tagged but never registered.
    assert registered | {"state_delta"} == tagged
    assert not set(DEDICATED) & set(SHARED)
    assert all(bucket in BUCKETS for bucket in DEDICATED.values())


def test_buckets_for_dual_tagging():
    assert buckets_for("aoi_id_match") == ("retrieval",)
    assert buckets_for("agent_answer") == ("analysis", "explanation")
    assert buckets_for("date_coverage") == ()  # info-only, unattributed


def test_row_verdicts():
    assert row_verdict({"checks": {"aoi_id_match": 1.0, "agent_answer": 1.0}}) == "pass"
    assert row_verdict({"checks": {"aoi_id_match": 1.0, "agent_answer": 0.0}}) == "fail"
    assert row_verdict({"checks": {"aoi_id_match": None}}) == "uncovered"
    assert row_verdict({"checks": {}}) == "uncovered"
    # info-only failures never make a verdict, and never hide as a pass
    assert row_verdict({"checks": {"date_coverage": 0.0}}) == "uncovered"
    assert (
        row_verdict({"checks": {"aoi_id_match": 1.0}, "judge_errors": ["agent_answer"]})
        == "error"
    )
    assert row_verdict({"checks": {"aoi_id_match": 1.0}, "error": "timeout"}) == "error"


def test_summarize_dual_tagged_checks_count_in_both_buckets():
    entries = [
        {"checks": {"charts_answer": 0.0, "aoi_id_match": 1.0}},
        {"checks": {"charts_answer": 1.0}},
    ]
    summary = summarize_buckets(entries)
    assert summary["analysis"]["shared"] == {"passed": 1, "evaluated": 2}
    assert summary["output"]["shared"] == {"passed": 1, "evaluated": 2}
    assert summary["analysis"]["dedicated"] == {"passed": 0, "evaluated": 0}
    assert summary["retrieval"]["dedicated"] == {"passed": 1, "evaluated": 1}
    assert summary["analysis"]["rows_covered"] == 2
    assert summary["retrieval"]["rows_covered"] == 1
    assert summary["verdicts"] == {"pass": 1, "fail": 1, "error": 0, "uncovered": 0}


def test_errored_entries_bank_no_bucket_tallies():
    """A conversation that errored partway must not add its earlier turns'
    passes and failures to bucket tallies or coverage. This matches
    `row_verdict`, which treats an errored row as an error, not a
    measurement. Verdict counts still include the entry, so the error stays
    visible."""
    entries = [
        {
            "checks": {"t1.aoi_id_match": 1.0, "t1.charts_answer": 1.0},
            "error": "t2: timeout",
        },
        {"checks": {"aoi_id_match": 1.0}},
    ]
    summary = summarize_buckets(entries)
    assert summary["retrieval"]["dedicated"] == {"passed": 1, "evaluated": 1}
    assert summary["analysis"]["shared"] == {"passed": 0, "evaluated": 0}
    assert summary["output"]["shared"] == {"passed": 0, "evaluated": 0}
    assert summary["retrieval"]["rows_covered"] == 1
    assert summary["analysis"]["rows_covered"] == 0
    assert summary["verdicts"] == {"pass": 1, "fail": 0, "error": 1, "uncovered": 0}


def test_implied_checks_from_expectations():
    implied = implied_checks({"answer": "42 ha", "aoi_ids": "BRA", "dataset_id": "4"})
    assert implied == {
        "agent_answer",
        "chart_produced",
        "data_pull_exists",
        "answered_without_data",
        "aoi_id_match",
        "dataset_id_match",
    }
    # a clarification row expects no pull
    assert implied_checks({"answer": "x", "clarification": "TRUE"}) == {
        "agent_answer",
        "chart_produced",
        "clarification_requested",
    }
    # a map-only dashboard implies no pull; an insight widget does
    assert "data_pull_exists" not in implied_checks({"dashboard_widgets": "map"})
    assert "data_pull_exists" in implied_checks({"dashboard_widgets": "insight;map"})
    # class_values, chart_type and scope each imply exactly their dedicated
    # check. The assertions use equality, so a mistyped field name in
    # implied_checks fails here.
    assert implied_checks({"class_values": "Natural=2,124 ha"}) == {"class_value_match"}
    assert implied_checks({"chart_type": "pie;table"}) == {"chart_type_match"}
    assert implied_checks({"scope": "analyse"}) == {"scope_match"}


def test_reconcile_itemises_every_hole():
    entries = [
        {
            "uid": "u1",
            "id": "1-001",
            "checks": {
                "agent_answer": 1.0,
                "chart_produced": None,
                "data_pull_exists": 1.0,
                "answered_without_data": 1.0,
            },
        },
        {"uid": "zz", "id": "1-999", "checks": {}},
    ]
    expected_by_uid = {"u1": {"answer": "42 ha"}}
    report = reconcile(entries, expected_by_uid)
    assert report["implied"] == 4
    assert report["evaluated_of_implied"] == 3
    assert report["missing"] == [
        {"id": "1-001", "uid": "u1", "check": "chart_produced"}
    ]
    assert report["rows_not_in_store"] == 1
