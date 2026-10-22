"""Ledger contract semantics."""

import pytest

from goldset.ledger import (
    check_name_from_column,
    majority,
    majority_from_mean,
    make_run_id,
    parse_score,
    read_run,
    reason_name_from_column,
    validate_run,
    write_run,
)

RUN = {
    "run_id": "20260731T120022Z_staging_experimental",
    "started": "2026-07-31T12:00:22Z",
    "environment": "staging",
    "build": "GNW 2026.7.29.1",
    "ff": "experimental",
    "harness": {"repo": "gnw-evals", "sha": "unknown"},
    "judge_model": "claude-haiku-4-5",
    "num_trials": 1,
    "caseset_version": "2f8b10272938527c",
    "results": [
        {
            "uid": "0fa55d427af482af",
            "id": "1-002",
            "checks": {"aoi_id_match": 1.0, "agent_answer": 0.0, "nudge_match": None},
        }
    ],
}


def test_column_mapping():
    assert check_name_from_column("aoi_id_match_score") == "aoi_id_match"
    assert check_name_from_column("overall_score") is None
    assert check_name_from_column("agent_answer_score_std") is None
    assert check_name_from_column("duration_seconds") is None
    assert reason_name_from_column("agent_answer_score_reason") == "agent_answer"
    # the gnw-evals naming quirk: reason stem differs from the score name
    assert reason_name_from_column("chart_answer_score_reason") == "charts_answer"


def test_parse_score_tri_state():
    assert parse_score("") is None
    assert parse_score(None) is None
    assert parse_score("1.0") == 1.0
    assert parse_score("0.0") == 0.0
    with pytest.raises(ValueError, match="binary"):
        parse_score("0.5")


def test_majority():
    assert majority([1.0, 1.0, 0.0]) == 1.0
    assert majority([1.0, 0.0]) == 0.0  # ties fail conservatively
    assert majority([None, None]) is None
    assert majority([None, 1.0]) == 1.0


def test_majority_from_mean():
    assert majority_from_mean("", 3) is None
    assert majority_from_mean(None, 3) is None
    assert majority_from_mean("0.6667", 3) == 1.0
    assert majority_from_mean("0.3333", 3) == 0.0
    assert majority_from_mean("0.5", 2) == 0.0  # ties fail conservatively
    assert majority_from_mean("1.0", 3) == 1.0
    with pytest.raises(ValueError, match="binary"):
        majority_from_mean("0.4", 3)  # not a whole number of passes


def test_make_run_id():
    assert (
        make_run_id("2026-07-31T12:00:22Z", "staging", "experimental")
        == "20260731T120022Z_staging_experimental"
    )
    assert make_run_id("2026-07-31T12:00:22", "prod", None) == "20260731T120022Z_prod"
    with pytest.raises(ValueError, match="run_id"):
        make_run_id("yesterday", "staging", None)


def test_validate_and_round_trip(tmp_path):
    assert validate_run(RUN) == []
    path = write_run(tmp_path, RUN)
    assert path.name == "20260731T120022Z_staging_experimental.json"
    assert read_run(path) == RUN


def test_validate_rejects_bad_records(tmp_path):
    assert "missing field: build" in validate_run(
        {k: v for k, v in RUN.items() if k != "build"}
    )
    no_uid = {**RUN, "results": [{"id": "x", "checks": {"a": 1.0}}]}
    assert any("not marked stale_case" in p for p in validate_run(no_uid))
    non_tri = {**RUN, "results": [{"uid": "u", "id": "x", "checks": {"a": 0.5}}]}
    assert any("not tri-state" in p for p in validate_run(non_tri))
    with pytest.raises(ValueError, match="invalid run"):
        write_run(tmp_path, non_tri)


def test_validate_rejects_non_float_checks():
    # bool == float equivalence must not let True/1 pass as tri-state
    for bad in (True, False, 1, 0, "1.0"):
        run = {**RUN, "results": [{"uid": "u", "id": "x", "checks": {"a": bad}}]}
        assert any("not tri-state" in p for p in validate_run(run)), repr(bad)


def test_write_run_refuses_divergent_overwrite(tmp_path):
    write_run(tmp_path, RUN)
    write_run(tmp_path, RUN)  # identical re-write is fine (idempotent)
    with pytest.raises(ValueError, match="immutable"):
        write_run(tmp_path, {**RUN, "build": "GNW other"})
