"""Per-store uid rule for multi-turn deltas (MANIFEST.json uid_includes_deltas).

cases/v2 hashes each turn's deltas into the uid, so editing a delta
assertion mints a new version.
"""

import asyncio
import json
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from goldset import cli
from goldset.canonical import conversation_uid
from goldset.store import (
    UID_INCLUDES_DELTAS,
    Case,
    build_manifest,
    load_store,
    read_manifest,
    store_uid_includes_deltas,
    write_case,
    write_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "tools" / "check.py"

TURNS = (
    {
        "query": "How much tree cover loss did Brazil have in 2022?",
        "expected": {"aoi_ids": "BRA", "dataset_id": "4"},
    },
    {
        "query": "And for Indonesia?",
        "expected": {"aoi_ids": "IDN"},
        "deltas": {"changed": ["aoi_ids"], "retain": ["dataset_id", "start_date"]},
    },
)


def check(cases_dir: Path, *flags: str):
    return subprocess.run(
        [sys.executable, str(CHECK), "--cases-dir", str(cases_dir), *flags],
        capture_output=True,
        text=True,
    )


def make_store(tmp_path: Path, flagged: bool) -> Path:
    cases_dir = tmp_path / "cases"
    case = Case(
        id="mt-x",
        status="ready",
        group="multiturn",
        turns=TURNS,
        uid_includes_deltas=flagged,
    )
    write_case(cases_dir, case)
    write_manifest(cases_dir, build_manifest([case], "test", flagged))
    return cases_dir


def edit_turn2_deltas(cases_dir: Path, deltas: dict) -> Path:
    path = cases_dir / "multiturn" / "mt-x.yaml"
    raw = yaml.safe_load(path.read_text())
    raw["turns"][1]["deltas"] = deltas
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    return path


def stored_uid(path: Path) -> str:
    return yaml.safe_load(path.read_text())["uid"]


# --- the committed store


def test_v2_hashes_deltas_into_multiturn_uids():
    v2 = ROOT / "cases" / "v2"
    assert read_manifest(v2)[UID_INCLUDES_DELTAS] is True
    multiturn = [(c, u) for _p, c, u in load_store(v2) if c.is_multiturn]
    assert multiturn
    for case, stored in multiturn:
        assert case.uid_includes_deltas
        assert stored == case.uid == conversation_uid(case.turns, include_deltas=True)


# --- check.py honours the flag


def test_flagged_store_mints_a_new_uid_on_delta_edit(tmp_path):
    cases_dir = make_store(tmp_path, flagged=True)
    assert check(cases_dir).returncode == 0
    path = edit_turn2_deltas(cases_dir, {"changed": ["aoi_ids"]})
    before = stored_uid(path)

    stale = check(cases_dir)
    assert stale.returncode == 1
    assert "stored uid" in stale.stdout

    assert check(cases_dir, "--fix").returncode == 0
    assert stored_uid(path) != before
    assert read_manifest(cases_dir)[UID_INCLUDES_DELTAS] is True  # preserved
    assert check(cases_dir).returncode == 0


def test_flagged_store_ignores_delta_key_and_list_order(tmp_path):
    cases_dir = make_store(tmp_path, flagged=True)
    path = edit_turn2_deltas(
        cases_dir, {"retain": ["start_date", "dataset_id"], "changed": ["aoi_ids"]}
    )
    before = stored_uid(path)
    assert check(cases_dir).returncode == 0
    assert stored_uid(path) == before


def test_unflagged_store_ignores_delta_edits(tmp_path):
    cases_dir = make_store(tmp_path, flagged=False)
    edit_turn2_deltas(cases_dir, {"absent": ["context_layer"]})
    assert check(cases_dir).returncode == 0
    assert UID_INCLUDES_DELTAS not in read_manifest(cases_dir)


def test_fix_with_flag_turns_the_rule_on(tmp_path):
    cases_dir = make_store(tmp_path, flagged=False)
    path = cases_dir / "multiturn" / "mt-x.yaml"
    before = stored_uid(path)

    refused = check(cases_dir, "--uid-includes-deltas")
    assert refused.returncode == 2
    assert "needs --fix" in refused.stderr

    assert check(cases_dir, "--fix", "--uid-includes-deltas").returncode == 0
    assert read_manifest(cases_dir)[UID_INCLUDES_DELTAS] is True
    assert stored_uid(path) == conversation_uid(TURNS, include_deltas=True) != before
    assert check(cases_dir).returncode == 0


# --- store guards


def test_manifest_refuses_cases_loaded_under_another_rule():
    case = Case(
        id="mt-x",
        status="ready",
        group="multiturn",
        turns=TURNS,
        uid_includes_deltas=True,
    )
    with pytest.raises(ValueError, match="uid_includes_deltas"):
        build_manifest([case], "test")


def test_non_boolean_flag_fails_loudly(tmp_path):
    cases_dir = make_store(tmp_path, flagged=False)
    manifest = read_manifest(cases_dir)
    manifest[UID_INCLUDES_DELTAS] = "yes"
    (cases_dir / "MANIFEST.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="must be true or false"):
        store_uid_includes_deltas(cases_dir)


# --- the runner's template resolution keeps the store's rule


def test_resolved_multiturn_case_keeps_the_store_rule(tmp_path, monkeypatch):
    templated = (
        {**TURNS[0], "query": "Tree cover loss in Brazil in {current_year}?"},
        TURNS[1],
    )
    case = Case(
        id="mt-x",
        status="ready",
        group="multiturn",
        turns=templated,
        uid_includes_deltas=True,
    )
    seen = []

    async def fake_conversation(
        runner, resolved, result_to_entry, artifact_sink_factory=None
    ):
        seen.append(resolved)
        return {
            "uid": resolved.uid,
            "id": resolved.id,
            "checks": {"t2.state_delta": 1.0},
        }

    class FakeRunner:
        def __init__(self, **kwargs):
            pass

    monkeypatch.setattr("goldset.runner.multiturn.run_conversation", fake_conversation)
    monkeypatch.setattr("goldset.runner.api.APITestRunner", FakeRunner)
    args = Namespace(
        resolved_url="http://localhost",
        api_token="t",
        ff=None,
        verbose=False,
        trial_timeout=60.0,
        results_dir=tmp_path,
        run_id="20261005T000000Z_local",
        workers=1,
        trials=1,
        slow_threshold=180.0,
        ground_truth={},
    )
    [entry] = asyncio.run(cli.run_cases(args, [case]))

    [resolved] = seen
    assert resolved.uid_includes_deltas
    assert "{current_year}" not in resolved.turns[0]["query"]
    assert resolved.turns[1]["deltas"] == TURNS[1]["deltas"]
    assert entry["uid"] == case.uid == conversation_uid(templated, include_deltas=True)
