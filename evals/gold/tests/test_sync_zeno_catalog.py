"""Catalogue snapshot extraction: trimming project-zeno catalogue YAMLs."""

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from sync_zeno_catalog import INSTRUCTION_FIELDS, snapshot_entry, sort_datasets

RAW = {
    "dataset_id": 4,
    "dataset_name": "Tree cover loss",
    "parameters": [
        {"name": "canopy_cover", "values": [10, 30], "description": "dropped"},
    ],
    "context_layers": [
        {"value": "primary_forest", "description": "dropped"},
        {"value": "intact_forest"},
    ],
    "content_date": "2001-2025 annual",
    "content_date_fixed": False,
    "start_date": date(2001, 1, 1),  # unquoted in the YAML: parses as a date
    "end_date": "2025-12-31",
    "analytics_api_endpoint": "/v0/land_change/tree_cover_loss/analytics",
    "prompt_instructions": "Reports gross annual loss...",
    "selection_hints": "Best dataset for annual loss...",
    "code_instructions": "CHART TYPES: ...",
    "presentation_instructions": "Use tree cover loss...",
    "methodology": "dropped entirely",
}


def test_snapshot_entry_trims_to_coverage_fields():
    entry = snapshot_entry(RAW, "tree_cover_loss.yml")
    assert entry == {
        "dataset_id": "4",
        "dataset_name": "Tree cover loss",
        "parameters": [{"name": "canopy_cover", "values": [10, 30]}],
        "context_layers": ["primary_forest", "intact_forest"],
        "instructions": list(INSTRUCTION_FIELDS),
        "analytics_api_endpoint": "/v0/land_change/tree_cover_loss/analytics",
        "content_date": "2001-2025 annual",
        "content_date_fixed": False,
        "start_date": "2001-01-01",
        "end_date": "2025-12-31",
    }


def test_an_open_ended_window_keeps_none_rather_than_empty_string():
    """`end_date` absent means "to today"; the request builder tells that apart
    from an empty one, so it must not be flattened to ''."""
    entry = snapshot_entry({k: v for k, v in RAW.items() if k != "end_date"}, "f.yml")
    assert entry["end_date"] is None
    assert (
        snapshot_entry({**RAW, "analytics_api_endpoint": "  "}, "f.yml")[
            "analytics_api_endpoint"
        ]
        is None
    )


def test_snapshot_entry_records_missing_instructions():
    raw = {**RAW, "code_instructions": "  ", "selection_hints": None}
    entry = snapshot_entry(raw, "f.yml")
    assert entry["instructions"] == ["prompt_instructions", "presentation_instructions"]


@pytest.mark.parametrize("missing", ["dataset_id", "dataset_name"])
def test_snapshot_entry_requires_identity(missing):
    raw = {k: v for k, v in RAW.items() if k != missing}
    with pytest.raises(ValueError, match="f.yml"):
        snapshot_entry(raw, "f.yml")


def test_sort_datasets_is_numeric_then_lexical():
    entries = [{"dataset_id": i} for i in ("10", "2", "x", "0")]
    assert [d["dataset_id"] for d in sort_datasets(entries)] == ["0", "2", "10", "x"]
