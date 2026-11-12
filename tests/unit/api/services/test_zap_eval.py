"""Checks for the zap eval set and the scoring of scripts/zap_eval.py.

The eval itself calls jev live and is not run here.
"""

import importlib.util
from datetime import date
from pathlib import Path

import pytest

from src.api.services.zap.models import ZapPlan, ZapStep
from src.api.services.zap.planner import CATALOG

ROOT = Path(__file__).resolve().parents[4]
_spec = importlib.util.spec_from_file_location(
    "zap_eval", ROOT / "scripts" / "zap_eval.py"
)
zap_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(zap_eval)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    import src.agent.datasets.dates as dates

    class _Date(date):
        @classmethod
        def today(cls):
            return date(2026, 11, 12)

    monkeypatch.setattr(dates, "date", _Date)


@pytest.mark.parametrize("part", ["dev", "test"])
def test_cases_are_valid(part):
    today, cases = zap_eval.load_part(part)
    assert today == date(2026, 11, 12)
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids))
    for case in cases:
        assert case["prompt"] and case["kind"] and case["tests"]
        assert set(case["tests"]) <= set(zap_eval.FIELDS), case["id"]
        exp = zap_eval.expected_state(case)
        for ds in exp["dataset"]:
            assert ds is None or ds in CATALOG, case["id"]
        for area in exp["area"]:
            assert area is None or ":" in area, case["id"]
        if case.get("follows"):
            assert case["follows"] in ids
            assert case.get("current"), case["id"]
        zap_eval.zap_current(case)


def test_parts_do_not_share_prompts():
    _, dev = zap_eval.load_part("dev")
    _, test = zap_eval.load_part("test")
    assert not {c["prompt"] for c in dev} & {c["prompt"] for c in test}


FOLLOW_UP = {
    "id": "x",
    "prompt": "since 2015",
    "current": {
        "dataset": 4,
        "area": {"id": "gadm:BRA.14_1", "name": "Pará"},
        "start": "2002-01-01",
        "end": "2025-12-31",
        "context": "primary_forest",
    },
    "expect": {"start": "2015-01-01", "end": "2026-11-12"},
}


def _dataset_step(dataset_id, start, end, context=None, canopy=None):
    params = [{"name": "canopy_cover", "values": [canopy]}] if canopy else None
    return ZapStep(
        kind="dataset",
        title="",
        args={
            "dataset_id": dataset_id,
            "start_date": start,
            "end_date": end,
            "context_layer": context,
            "parameters": params,
        },
    )


def test_expected_state_keeps_current():
    exp = zap_eval.expected_state(FOLLOW_UP)
    assert exp["dataset"] == [4]
    assert exp["area"] == ["gadm:BRA.14_1"]
    assert exp["context"] == ["primary_forest"]
    assert exp["ranges"] == [("2015-01-01", "2026-11-12")]


@pytest.mark.asyncio
async def test_lost_context_fails_only_context():
    plan = ZapPlan(
        steps=[_dataset_step(4, "2015-01-01", "2025-12-31")], decisions=[]
    )
    got = zap_eval.state_after(FOLLOW_UP, plan)
    assert got["area"] == "gadm:BRA.14_1"
    scores = await zap_eval.score(FOLLOW_UP, got, plan)
    assert scores["dataset"] and scores["area"] and scores["time"]
    assert scores["context"] is False
    assert scores["canopy"] is True
    assert scores["no_change"] is None


@pytest.mark.asyncio
async def test_no_steps_keeps_the_map():
    case = {**FOLLOW_UP, "expect": {}, "no_change": True}
    plan = ZapPlan(steps=[], decisions=[])
    got = zap_eval.state_after(case, plan)
    scores = await zap_eval.score(case, got, plan)
    assert all(v for v in scores.values() if v is not None)
    assert scores["no_change"] is True


@pytest.mark.asyncio
async def test_relative_range_tolerance():
    case = {
        "id": "x",
        "prompt": "alerts in the last 3 months",
        "expect": {
            "dataset": 11,
            "start": "2026-08-12",
            "end": "2026-11-12",
            "relative": True,
        },
    }
    exp = zap_eval.expected_state(case)
    near = {
        "dataset": 11,
        "context": None,
        "start": "2026-08-01",
        "end": "2026-11-12",
    }
    far = {**near, "start": "2025-11-12"}
    assert await zap_eval.range_ok(near, exp)
    assert not await zap_eval.range_ok(far, exp)


@pytest.mark.asyncio
async def test_fixed_range_is_clamped_to_the_dataset():
    case = {
        "id": "x",
        "prompt": "loss since 2015",
        "expect": {"dataset": 4, "start": "2015-01-01", "end": "2026-11-12"},
    }
    exp = zap_eval.expected_state(case)
    got = {
        "dataset": 4,
        "context": None,
        "start": "2015-01-01",
        "end": "2025-12-31",
    }
    assert await zap_eval.range_ok(got, exp)
    assert not await zap_eval.range_ok({**got, "start": "2014-01-01"}, exp)


@pytest.mark.asyncio
async def test_canopy_default_is_30():
    case = {"id": "x", "prompt": "p", "expect": {"dataset": 4, "canopy": 30}}
    plan = ZapPlan(
        steps=[_dataset_step(4, "2001-01-01", "2025-12-31")], decisions=[]
    )
    got = zap_eval.state_after(case, plan)
    assert (await zap_eval.score(case, got, plan))["canopy"] is True
