"""Resume flow: the in-flight partial ledger and the --resume CLI path.

A run appends one fsynced JSONL line per completed case so a killed run
loses at most the case that was mid-write; --resume reconstructs the run's
config from the partial's header line and runs only what's missing.
"""

from __future__ import annotations

import argparse
import json

import pytest

from goldset import cli
from goldset.ledger import (
    append_partial_entry,
    partial_path,
    read_partial,
    read_run,
    write_partial_header,
)
from goldset.store import Case, build_manifest, write_case, write_manifest


def make_header(**overrides) -> dict:
    header = {
        "run_id": "20260831T143429Z_prod_experimental",
        "started": "2026-08-31T14:34:29Z",
        "environment": "prod",
        "resolved_url": "https://api.globalnaturewatch.org",
        "ff": "experimental",
        "build": "baseline",
        "trials": 3,
        "workers": 10,
        "trial_timeout": 900.0,
        "slow_threshold": 180.0,
        "cases_dir": "cases/v2",
        "caseset_version": "2f8b10272938527c",
        "status_exclude": "not doing",
        "id": None,
        "group": None,
        "note": None,
    }
    return {**header, **overrides}


ENTRY_A = {"uid": "a" * 16, "id": "1-001", "checks": {"aoi_id_match": 1.0}}
ENTRY_B = {"uid": "b" * 16, "id": "1-002", "checks": {"aoi_id_match": 0.0}}


def test_partial_round_trip(tmp_path):
    header = make_header()
    path = write_partial_header(tmp_path, header)
    assert path == partial_path(tmp_path, header["run_id"])
    append_partial_entry(path, ENTRY_A)
    append_partial_entry(path, ENTRY_B)
    read_header, entries = read_partial(path)
    assert read_header == header
    assert entries == [ENTRY_A, ENTRY_B]


def test_header_refuses_missing_fields(tmp_path):
    header = make_header()
    del header["caseset_version"]
    with pytest.raises(ValueError, match="missing fields"):
        write_partial_header(tmp_path, header)


def test_header_refuses_existing_partial(tmp_path):
    write_partial_header(tmp_path, make_header())
    with pytest.raises(ValueError, match="already exists"):
        write_partial_header(tmp_path, make_header())


def test_read_drops_truncated_final_line(tmp_path):
    path = write_partial_header(tmp_path, make_header())
    append_partial_entry(path, ENTRY_A)
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"uid": "cccccccccccccccc", "checks": {"aoi')
    _, entries = read_partial(path)
    assert entries == [ENTRY_A]


def test_read_refuses_corrupt_middle_line(tmp_path):
    path = write_partial_header(tmp_path, make_header())
    with path.open("a", encoding="utf-8") as handle:
        handle.write("not json\n")
        handle.write(json.dumps(ENTRY_A) + "\n")
    with pytest.raises(ValueError, match="corrupt line mid-file"):
        read_partial(path)


def test_read_refuses_duplicate_uids(tmp_path):
    path = write_partial_header(tmp_path, make_header())
    append_partial_entry(path, ENTRY_A)
    append_partial_entry(path, {**ENTRY_A, "checks": {"aoi_id_match": 0.0}})
    with pytest.raises(ValueError, match="duplicate entry"):
        read_partial(path)


def test_read_refuses_entry_without_uid(tmp_path):
    path = write_partial_header(tmp_path, make_header())
    append_partial_entry(path, {"id": "1-001", "checks": {}})
    with pytest.raises(ValueError, match="without uid/checks"):
        read_partial(path)


def test_read_refuses_entry_first_line(tmp_path):
    path = partial_path(tmp_path, "x")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(ENTRY_A) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not a run header"):
        read_partial(path)


def test_read_refuses_empty_file(tmp_path):
    path = partial_path(tmp_path, "x")
    path.parent.mkdir(parents=True)
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        read_partial(path)


# --- the --resume CLI path -------------------------------------------------

RUN_ID = "20260831T143429Z_prod_experimental"

CASE_A = Case(
    id="1-001",
    status="ready",
    group="direct",
    query="q one",
    expected={"dataset_id": "4"},
)
CASE_B = Case(
    id="1-002",
    status="ready",
    group="direct",
    query="q two",
    expected={"dataset_id": "11"},
)


def make_store(tmp_path):
    cases_dir = tmp_path / "cases" / "v2"
    for case in (CASE_A, CASE_B):
        write_case(cases_dir, case)
    manifest = build_manifest([CASE_A, CASE_B], source="test")
    write_manifest(cases_dir, manifest)
    return cases_dir, manifest


def entry_for(case: Case, score: float = 1.0) -> dict:
    return {"uid": case.uid, "id": case.id, "checks": {"dataset_id_match": score}}


def make_partial(tmp_path, cases_dir, manifest, done: list[dict]):
    header = make_header(
        run_id=RUN_ID,
        trials=1,
        cases_dir=str(cases_dir),
        caseset_version=manifest["caseset_version"],
    )
    path = write_partial_header(tmp_path / "results", header)
    for entry in done:
        append_partial_entry(path, entry)
    return path


def resume_args(tmp_path) -> argparse.Namespace:
    return argparse.Namespace(resume=RUN_ID, results_dir=tmp_path / "results")


@pytest.fixture
def hermetic(monkeypatch):
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.setenv("API_TOKEN", "test-token")


def test_resume_runs_only_missing_cases(tmp_path, monkeypatch, hermetic):
    cases_dir, manifest = make_store(tmp_path)
    partial = make_partial(tmp_path, cases_dir, manifest, [entry_for(CASE_A)])
    seen: list[list[Case]] = []

    async def fake_run_cases(args, cases, entry_sink=None):
        seen.append(cases)
        entries = [entry_for(case, score=0.0) for case in cases]
        for entry in entries:
            entry_sink(entry)
        return entries

    monkeypatch.setattr(cli, "run_cases", fake_run_cases)
    assert cli.resume_run(resume_args(tmp_path)) == 0

    assert [c.uid for c in seen[0]] == [CASE_B.uid]
    record = read_run(tmp_path / "results" / "runs" / f"{RUN_ID}.json")
    assert record["resumed"] is True
    assert [e["id"] for e in record["results"]] == ["1-001", "1-002"]
    assert record["results"][0]["checks"] == {"dataset_id_match": 1.0}
    assert record["results"][1]["checks"] == {"dataset_id_match": 0.0}
    assert record["caseset_version"] == manifest["caseset_version"]
    assert not partial.exists()


def test_resume_finalises_when_nothing_remains(tmp_path, monkeypatch, hermetic):
    cases_dir, manifest = make_store(tmp_path)
    partial = make_partial(
        tmp_path, cases_dir, manifest, [entry_for(CASE_A), entry_for(CASE_B)]
    )

    async def unexpected(*a, **kw):  # pragma: no cover - failure path
        raise AssertionError("run_cases must not be called")

    monkeypatch.setattr(cli, "run_cases", unexpected)
    assert cli.resume_run(resume_args(tmp_path)) == 0
    record = read_run(tmp_path / "results" / "runs" / f"{RUN_ID}.json")
    assert record["resumed"] is True
    assert len(record["results"]) == 2
    assert not partial.exists()


def test_resume_restores_the_analytics_host_and_sums_prefetch_time(
    tmp_path, monkeypatch, hermetic
):
    """A run started against a custom analytics host must not resume against
    the default one — resume ignores flags, so the header has to carry it."""
    import goldset.groundtruth

    gt_case = Case(
        id="1-046",
        status="ready",
        group="direct",
        query="q gt",
        expected={
            "aoi_ids": "MDG.3.4_1",
            "aoi_source": "gadm",
            "dataset_id": "4",
            "ground_truth": "sum(area_ha)",
        },
    )
    cases_dir = tmp_path / "cases" / "v2"
    for case in (CASE_A, gt_case):
        write_case(cases_dir, case)
    manifest = build_manifest([CASE_A, gt_case], source="test")
    write_manifest(cases_dir, manifest)
    path = write_partial_header(
        tmp_path / "results",
        make_header(
            run_id=RUN_ID,
            trials=1,
            cases_dir=str(cases_dir),
            caseset_version=manifest["caseset_version"],
            analytics_base_url="https://analytics.custom",
            prefetch_seconds=2.0,
        ),
    )
    append_partial_entry(path, entry_for(CASE_A))

    hosts: list[str] = []

    def fake_prefetch(targets, client, verbose=False):
        hosts.append(client.base_url)
        return {}

    async def fake_run_cases(args, cases, entry_sink=None):
        entries = [
            {**entry_for(case), "ground_truth": {"values": [1.0]}} for case in cases
        ]
        for entry in entries:
            entry_sink(entry)
        return entries

    monkeypatch.setattr(goldset.groundtruth, "prefetch", fake_prefetch)
    monkeypatch.setattr(cli, "run_cases", fake_run_cases)
    args = resume_args(tmp_path)
    args.verbose = False  # argparse always sets it; prefetch reads it
    assert cli.resume_run(args) == 0

    assert hosts == ["https://analytics.custom"]
    record = read_run(tmp_path / "results" / "runs" / f"{RUN_ID}.json")
    assert record["ground_truth"]["base_url"] == "https://analytics.custom"
    assert record["ground_truth"]["cases"] == 1
    assert record["ground_truth"]["prefetch_seconds"] >= 2.0  # first session kept


def test_resume_refuses_caseset_drift(tmp_path, hermetic):
    cases_dir, manifest = make_store(tmp_path)
    partial = make_partial(tmp_path, cases_dir, manifest, [entry_for(CASE_A)])
    case_c = Case(
        id="1-003",
        status="ready",
        group="direct",
        query="q three",
        expected={"dataset_id": "0"},
    )
    write_case(cases_dir, case_c)
    write_manifest(cases_dir, build_manifest([CASE_A, CASE_B, case_c], source="test"))

    assert cli.resume_run(resume_args(tmp_path)) == 1
    assert partial.exists()
    assert not (tmp_path / "results" / "runs" / f"{RUN_ID}.json").exists()


def test_resume_without_partial(tmp_path, capsys):
    assert cli.resume_run(resume_args(tmp_path)) == 1
    assert "nothing to resume" in capsys.readouterr().out


def test_resume_removes_stale_partial_after_finalised_run(tmp_path, hermetic):
    cases_dir, manifest = make_store(tmp_path)
    partial = make_partial(tmp_path, cases_dir, manifest, [entry_for(CASE_A)])
    final = tmp_path / "results" / "runs" / f"{RUN_ID}.json"
    final.write_text("{}", encoding="utf-8")

    assert cli.resume_run(resume_args(tmp_path)) == 0
    assert not partial.exists()
    assert final.read_text(encoding="utf-8") == "{}"
