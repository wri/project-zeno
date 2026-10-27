"""Unit tests for tools/compose_runs.py.

The composition exists because the ledger contract forbids the obvious shortcut
(writing later scores into an earlier run file), so the properties that matter are:
freshest-measurement-wins, current-uid-only, nothing silently dropped, and no
ledger file written.
"""

import importlib.util
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
_spec = importlib.util.spec_from_file_location(
    "compose_runs", ROOT / "tools" / "compose_runs.py"
)
compose_runs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compose_runs)

from goldset.canonical import case_uid  # noqa: E402


def _case(tmp_path: Path, case_id: str, query: str, status: str = "done") -> str:
    expected = {"aoi_ids": "BRA", "scope": "analyse"}
    uid = case_uid(query, expected)
    group = tmp_path / "direct"
    group.mkdir(parents=True, exist_ok=True)
    (group / f"{case_id}.yaml").write_text(
        yaml.safe_dump(
            {
                "id": case_id,
                "uid": uid,
                "status": status,
                "group": "direct",
                "query": query,
                "expected": expected,
            },
            sort_keys=False,
        ),
    )
    return uid


def _run(run_id: str, entries: list[dict], ff: str | None = "experimental") -> dict:
    return {
        "run_id": run_id,
        "started": "2026-08-03T00:00:00Z",
        "environment": "staging",
        "build": "b",
        "ff": ff,
        "harness": {"repo": "gnw-gold-evals", "sha": "x"},
        "judge_model": "m",
        "num_trials": 3,
        "caseset_version": "deadbeef",
        "results": entries,
    }


def _entry(case_id: str, uid: str, passing: bool) -> dict:
    checks = {"scope_match": 1.0 if passing else 0.0, "aoi_id_match": 1.0}
    return {
        "id": case_id,
        "uid": uid,
        "checks": checks,
        "trials": [{"checks": checks}] * 3,
    }


def test_supplementary_run_overrides_the_primary(tmp_path):
    uid = _case(tmp_path, "1-001", "q one")
    primary = _run("A_staging", [_entry("1-001", uid, passing=False)])
    supp = _run("B_staging", [_entry("1-001", uid, passing=True)])
    report = compose_runs.compose(primary, [supp], tmp_path)
    assert report["verdicts"] == {"pass": 1}
    assert report["rows"][0]["source"] == "B_staging"


def test_later_supplement_wins_over_earlier(tmp_path):
    uid = _case(tmp_path, "1-001", "q one")
    primary = _run("A", [_entry("1-001", uid, passing=False)])
    first = _run("B", [_entry("1-001", uid, passing=False)])
    second = _run("C", [_entry("1-001", uid, passing=True)])
    report = compose_runs.compose(primary, [first, second], tmp_path)
    assert report["rows"][0]["source"] == "C"


def test_rows_the_primary_still_owns_are_kept(tmp_path):
    uid_a = _case(tmp_path, "1-001", "q one")
    uid_b = _case(tmp_path, "1-002", "q two")
    primary = _run("A", [_entry("1-001", uid_a, True), _entry("1-002", uid_b, True)])
    supp = _run("B", [_entry("1-002", uid_b, False)])
    report = compose_runs.compose(primary, [supp], tmp_path)
    assert report["measured"] == 2
    by_id = {row["id"]: row for row in report["rows"]}
    assert by_id["1-001"]["source"] == "A"
    assert by_id["1-002"]["source"] == "B"


def test_a_superseded_uid_is_not_counted(tmp_path):
    """The whole point of keying on uid: an entry for an edited case must not
    be attributed to the new content."""
    uid = _case(tmp_path, "1-001", "q one")
    primary = _run("A", [_entry("1-001", "0" * 16, passing=True)])  # old uid
    report = compose_runs.compose(primary, [], tmp_path)
    assert report["measured"] == 0
    assert report["unmeasured"] == ["1-001"]
    assert uid  # the current uid simply has no measurement


def test_unmeasured_rows_are_reported_not_dropped(tmp_path):
    _case(tmp_path, "1-001", "q one")
    uid_b = _case(tmp_path, "1-002", "q two")
    primary = _run("A", [_entry("1-002", uid_b, passing=True)])
    report = compose_runs.compose(primary, [], tmp_path)
    assert report["unmeasured"] == ["1-001"]
    assert "unmeasured at their current uid (1)" in compose_runs.render(report)


def test_parked_cases_are_excluded(tmp_path):
    _case(tmp_path, "1-001", "q one", status="not doing")
    uid_b = _case(tmp_path, "1-002", "q two")
    primary = _run("A", [_entry("1-002", uid_b, passing=True)])
    report = compose_runs.compose(primary, [], tmp_path)
    assert report["active_cases"] == 1
    assert report["unmeasured"] == []


def test_mixed_ff_across_sources_is_flagged_loudly(tmp_path):
    uid = _case(tmp_path, "1-001", "q one")
    primary = _run("A", [_entry("1-001", uid, passing=True)], ff=None)
    supp = _run("B", [_entry("1-001", uid, passing=True)], ff="experimental")
    rendered = compose_runs.render(compose_runs.compose(primary, [supp], tmp_path))
    assert "Sources disagree on `ff`" in rendered
    assert "**unset**" in rendered
    # The rule that still holds since the default profile gained dashboards
    # and imagery (2026-08-31): never compose across differing ff.
    assert "must never be composed" in rendered
    assert "dashboards" not in rendered


def test_composition_writes_no_ledger_file(tmp_path):
    """The contract forbids backfilled runs; composing must stay read-only."""
    uid = _case(tmp_path, "1-001", "q one")
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    primary = _run("A", [_entry("1-001", uid, passing=True)])
    compose_runs.compose(primary, [], tmp_path)
    assert list(runs_dir.iterdir()) == []
