"""Every committed case file must conform to schema/case.schema.json."""

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema" / "case.schema.json").read_text())
CASE_FILES = sorted((ROOT / "cases").rglob("*.yaml"))


def test_schema_itself_is_valid():
    Draft202012Validator.check_schema(SCHEMA)


@pytest.mark.parametrize("path", CASE_FILES, ids=lambda p: p.stem)
def test_case_file_conforms(path):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(SCHEMA).iter_errors(data))
    assert not errors, "\n".join(e.message for e in errors)


def test_store_is_populated():
    assert CASE_FILES, "cases/ is empty — is cases/v2 missing or the glob wrong?"


def _multiturn_case(deltas):
    return {
        "id": "mt-t",
        "uid": "0" * 16,
        "status": "ready",
        "group": "multiturn",
        "turns": [
            {"query": "q1"},
            {"query": "q2", "deltas": deltas},
        ],
    }


def test_typoed_delta_field_fails_schema_validation():
    """A typo'd snapshot field (aoi_id vs aoi_ids) must fail at authoring
    time; before the enum it validated cleanly and silently abstained at
    runtime."""
    validator = Draft202012Validator(SCHEMA)
    assert list(validator.iter_errors(_multiturn_case({"changed": ["aoi_id"]})))
    assert not list(validator.iter_errors(_multiturn_case({"changed": ["aoi_ids"]})))


def test_schema_delta_enum_matches_snapshot_fields():
    """The schema's fieldList enum is a hand-maintained copy of the runner's
    SNAPSHOT_FIELDS; this test is the drift guard."""
    from goldset.runner.multiturn import SNAPSHOT_FIELDS

    enum = SCHEMA["$defs"]["fieldList"]["items"]["enum"]
    assert set(enum) == set(SNAPSHOT_FIELDS)
    assert len(enum) == len(set(enum))
