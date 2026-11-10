"""COVERAGE.md generation: derived content, freshness gate."""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from coverage_doc import render

from goldset.store import Case, build_manifest, write_case, write_manifest

CASES = [
    Case(
        id="1-001",
        status="done",
        group="direct",
        query="How much loss in X in 2022?",
        expected={
            "aoi_ids": "BRA",
            "dataset_id": "4",
            "answer": "1,000 ha",
            "scope": "analyse",
        },
    ),
    Case(
        id="1-002",
        status="not doing",
        group="direct",
        query="parked",
        expected={"answer": "n/a"},
        notes={"status_reason": "parked without a recorded reason"},
    ),
    Case(
        id="mt-001",
        status="ready",
        group="multiturn",
        turns=(
            {"query": "alerts in Puri", "expected": {"clarification": "TRUE"}},
            {
                "query": "Odisha one",
                "expected": {"scope": "analyse"},
                "deltas": {"changed": ["aoi_ids"]},
            },
        ),
    ),
]


def make_store(tmp_path: Path) -> Path:
    cases_dir = tmp_path / "v2"
    for case in CASES:
        write_case(cases_dir, case)
    write_manifest(cases_dir, build_manifest(CASES, "test"))
    return cases_dir


ALL_INSTRUCTIONS = [
    "prompt_instructions",
    "selection_hints",
    "code_instructions",
    "presentation_instructions",
]

CATALOG = {
    "source": {
        "repo": "git@github.com:wri/project-zeno.git",
        "ref": "origin/main",
        "sha": "abc1234def5678",
        "path": "src/agent/datasets/catalog",
        "synced": "2026-08-04",
    },
    "datasets": [
        {
            "dataset_id": "0",
            "dataset_name": "DIST-ALERT",
            "parameters": [],
            "context_layers": ["driver", "natural_lands"],
            "instructions": ALL_INSTRUCTIONS,
        },
        {
            "dataset_id": "4",
            "dataset_name": "Tree cover loss",
            "parameters": [{"name": "canopy_cover", "values": [10, 30]}],
            "context_layers": ["primary_forest", "intact_forest"],
            "instructions": ALL_INSTRUCTIONS,
        },
        {
            "dataset_id": "11",
            "dataset_name": "Integrated alerts",
            "parameters": [],
            "context_layers": [],
            "instructions": ["selection_hints"],
        },
    ],
}

DATASET_CASES = [
    Case(
        id="d-001",
        status="done",
        group="direct",
        query="loss at 10%?",
        expected={
            "dataset_id": "4",
            "answer": "1 ha",
            "context_layer": "primary_forest",
            "dataset_parameters": '[{"name": "canopy_cover", "values": [10]}]',
            "scope": "analyse",
        },
    ),
    Case(
        id="d-002",
        status="done",
        group="direct",
        query="alerts or loss?",
        expected={"dataset_id": "0;4", "scope": "analyse"},
    ),
    Case(
        id="d-003",
        status="done",
        group="direct",
        query="off catalog",
        expected={"dataset_id": "99", "answer": "2 ha", "scope": "analyse"},
    ),
    Case(
        id="d-004",
        status="not doing",
        group="direct",
        query="parked",
        expected={"dataset_id": "11", "answer": "3 ha"},
        notes={"status_reason": "parked"},
    ),
    Case(
        id="mt-d01",
        status="ready",
        group="multiturn",
        turns=(
            {
                "query": "alerts in Puri",
                "expected": {"dataset_id": "0", "clarification": "TRUE"},
            },
            {
                "query": "for Odisha",
                "expected": {"dataset_id": "0", "answer": "2 ha"},
                "deltas": {"changed": ["aoi_ids"]},
            },
        ),
    ),
]


def make_dataset_store(tmp_path: Path) -> Path:
    cases_dir = tmp_path / "v2"
    for case in DATASET_CASES:
        write_case(cases_dir, case)
    write_manifest(cases_dir, build_manifest(DATASET_CASES, "test"))
    (tmp_path / "zeno_catalog.json").write_text(json.dumps(CATALOG), encoding="utf-8")
    return cases_dir


def test_dataset_coverage_section(tmp_path):
    text = render(make_dataset_store(tmp_path))
    assert "## Dataset coverage (project-zeno catalog)" in text
    assert "project-zeno@abc1234" in text
    # d-002 pairs with both alternatives; only d-001 is answer-graded on 4
    assert (
        "| 4 | Tree cover loss | 2 | 1 | canopy_cover ×1 "
        "| primary_forest ×1, intact_forest ×0 ← gap |"
    ) in text
    # mt-d01 counts once, answer-graded via turn 2; layers untouched
    assert (
        "| 0 | DIST-ALERT | 2 | 1 | — " "| driver ×0 ← gap, natural_lands ×0 ← gap |"
    ) in text
    # d-004 is inactive, so 11 has no coverage; missing instructions surface
    assert (
        "| 11 | Integrated alerts (missing: code_instructions, "
        "presentation_instructions, prompt_instructions) | 0 ← gap | 0 | — | — |"
    ) in text
    # ids the catalogue does not know are flagged, not silently counted
    assert "not in the catalog: 99" in text
    # known gaps summarise unexercised catalogue features and empty datasets
    assert "- Catalog datasets with no active case: 11." in text
    assert (
        "- Catalog features no active case exercises — context layers: "
        "driver (0), natural_lands (0), intact_forest (4)."
    ) in text


def test_render_derives_content_and_coverage(tmp_path):
    text = render(make_store(tmp_path))
    # no snapshot in this store: the section points at the sync tool
    assert "No catalog snapshot found" in text
    assert "3 cases" in text and "**2 active**" in text
    assert "| direct | 2 | 1 | done 1, not doing 1 |" in text
    # 1-001 via dataset_id_match, mt-001 via t2.state_delta: both dedicated
    assert "| retrieval | 2 | 0 | 2 | 100% |" in text
    # analysis is reachable only via shared checks (1-001's answer judges)
    assert "| analysis | 0 | 1 | 1 | 50% |" in text
    # unused fields flagged so dead checks are visible
    assert "| chart_type | 0 ← unused | chart_type_match |" in text
    # parked case surfaces with its reason
    assert "| 1-002 | not doing | direct | parked without a recorded reason |" in text
    # multiturn census
    assert "1 active conversations (2 turns)" in text
    assert "changed ×1" in text


def test_check_mode_gates_freshness(tmp_path):
    cases_dir = make_store(tmp_path)
    tool = Path(__file__).resolve().parents[1] / "tools" / "coverage_doc.py"
    base = [sys.executable, str(tool), "--cases-dir", str(cases_dir)]
    assert subprocess.run(base, check=False).returncode == 0
    assert subprocess.run([*base, "--check"], check=False).returncode == 0
    doc = cases_dir / "COVERAGE.md"
    # the Last-updated stamp exists, and a date-only difference is not drift
    text = doc.read_text(encoding="utf-8")
    assert "_Last updated: " in text
    import re

    doc.write_text(
        re.sub(
            r"_Last updated: \d{4}-\d{2}-\d{2}_", "_Last updated: 2000-01-01_", text
        ),
        encoding="utf-8",
    )
    assert subprocess.run([*base, "--check"], check=False).returncode == 0
    # any real content change is drift
    doc.write_text(doc.read_text(encoding="utf-8") + "\ndrift\n", encoding="utf-8")
    assert subprocess.run([*base, "--check"], check=False).returncode == 1
