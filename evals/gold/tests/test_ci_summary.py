"""Tests for tools/ci_summary.py: the pass-rate headline, the threshold
annotation, and the summary for a run that wrote no record."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import ci_summary


def _run(verdicts: list[str]) -> dict:
    checks = {
        "pass": {"aoi_id_match": 1.0},
        "fail": {"aoi_id_match": 0.0},
        "uncovered": {"aoi_id_match": None},
    }
    results = []
    for i, verdict in enumerate(verdicts):
        entry = {"uid": f"u{i}", "id": f"1-{i:03d}"}
        if verdict == "error":
            entry["checks"] = {}
            entry["error"] = "ReadTimeout"
        else:
            entry["checks"] = checks[verdict]
        results.append(entry)
    return {
        "run_id": "20261017T120000Z_ephemeral",
        "build": "abc123",
        "num_trials": 3,
        "workers": 10,
        "trial_timeout": 900.0,
        "caseset_version": "cs1",
        "results": results,
    }


def test_above_threshold_is_green_with_no_annotation():
    markdown, annotation = ci_summary.render(_run(["pass"] * 10), 90, None)
    assert "🟢 Pass rate 100.0% (10/10)" in markdown
    assert "| 10 | 10 | 0 | 0 | 0 |" in markdown
    assert annotation is None


def test_errors_and_uncovered_count_against_the_rate():
    run = _run(["pass"] * 8 + ["error", "uncovered"])
    markdown, annotation = ci_summary.render(run, 90, None)
    assert "🔴 **Pass rate 80.0% (8/10), below the 90% threshold**" in markdown
    assert "| 10 | 8 | 0 | 1 | 1 |" in markdown
    assert annotation.startswith("::error title=GOLD pass rate::80.0%")


def test_exactly_at_threshold_is_green():
    _, annotation = ci_summary.render(_run(["pass"] * 9 + ["fail"]), 90, None)
    assert annotation is None


def test_lists_cases_not_passing():
    markdown, _ = ci_summary.render(_run(["pass", "fail", "error"]), 90, None)
    assert "**Failing:** 1-001" in markdown
    assert "**Errored:** 1-002" in markdown


def test_details_link():
    markdown, _ = ci_summary.render(_run(["pass"]), 90, "https://example/run/1")
    assert "[this run](https://example/run/1)" in markdown


def test_no_record_shows_the_log_tail(tmp_path):
    log = tmp_path / "gold.log"
    log.write_text("starting\nHTTP 401 Unauthorized\n")
    out = tmp_path / "summary.md"
    sys.argv = [
        "ci_summary.py",
        "--results-dir",
        str(tmp_path / "results"),
        "--out",
        str(out),
        "--log",
        str(log),
    ]
    assert ci_summary.main() == 0
    markdown = out.read_text()
    assert "did not complete" in markdown
    assert "HTTP 401 Unauthorized" in markdown


def test_find_run_ignores_partial_files(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "x.partial.jsonl").write_text("{}")
    assert ci_summary.find_run(tmp_path) is None
    (runs / "x.json").write_text("{}")
    assert ci_summary.find_run(tmp_path) == runs / "x.json"


def test_shows_the_most_common_error():
    markdown, _ = ci_summary.render(_run(["error", "error", "pass"]), 90, None)
    assert "Most common error (2 case(s)): `ReadTimeout`" in markdown


def test_no_error_line_without_errors():
    markdown, _ = ci_summary.render(_run(["pass", "fail"]), 90, None)
    assert "Most common error" not in markdown


def test_build_line_shows_workers_and_timeout():
    markdown, _ = ci_summary.render(_run(["pass"]), 90, None)
    assert "10 worker(s)" in markdown
    assert "900s trial timeout" in markdown


def test_build_line_tolerates_missing_workers_and_timeout():
    run = _run(["pass"])
    del run["workers"]
    del run["trial_timeout"]
    markdown, _ = ci_summary.render(run, 90, None)
    assert "None worker(s)" in markdown
    assert "n/a trial timeout" in markdown
