"""Efficiency metrics: capture from the thread state, ledger mapping,
multi-turn sums, and the comparison report. All info-only."""

import importlib.util
import json
from pathlib import Path

import httpx
import pytest
from langchain_core.load import dumps
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from goldset.adapter import case_to_expected
from goldset.buckets import row_verdict
from goldset.cli import merge_trials, result_to_entry
from goldset.efficiency import METRICS, sum_efficiency, turn_efficiency
from goldset.ledger import read_run, validate_run
from goldset.runner.api import APITestRunner
from goldset.runner.multiturn import run_conversation
from goldset.store import Case

USAGE = {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110}


def _turn(query, answer, usage=USAGE):
    """One turn: a tool call round trip, then the final answer."""
    return [
        HumanMessage(content=query),
        AIMessage(
            content="",
            tool_calls=[{"name": "pick_aoi", "args": {}, "id": "c1"}],
            usage_metadata=usage,
        ),
        ToolMessage(content="ok", tool_call_id="c1"),
        AIMessage(content=answer, usage_metadata=usage),
    ]


def test_turn_efficiency_counts_calls_answer_and_tokens():
    metrics = turn_efficiency(_turn("q", "one two three"), "q")
    assert metrics == {
        "model_calls": 2,
        "tool_calls": 1,
        "answer_words": 3,
        "answer_chars": 13,
        "input_tokens": 200,
        "output_tokens": 20,
    }


def test_turn_efficiency_counts_only_the_latest_turn():
    messages = _turn("first", "a b") + _turn("second", "c d e f")
    metrics = turn_efficiency(messages, "second")
    assert metrics["model_calls"] == 2
    assert metrics["answer_words"] == 4
    assert metrics["input_tokens"] == 200


def test_tokens_are_null_when_any_ai_message_lacks_usage():
    messages = _turn("q", "a")
    messages[3] = AIMessage(content="a")  # no usage_metadata
    metrics = turn_efficiency(messages, "q")
    assert metrics["input_tokens"] is None
    assert metrics["output_tokens"] is None
    assert metrics["model_calls"] == 2


def test_answer_is_null_when_the_turn_does_not_end_on_an_ai_message():
    metrics = turn_efficiency(_turn("q", "a")[:3], "q")
    assert metrics["answer_words"] is None
    assert metrics["answer_chars"] is None


def test_empty_state_gives_zero_calls_and_null_tokens():
    metrics = turn_efficiency([], "q")
    assert metrics["model_calls"] == 0
    assert metrics["input_tokens"] is None


def test_sum_efficiency_adds_and_keeps_null():
    a = {m: 1 for m in METRICS}
    b = {m: 2 for m in METRICS} | {"input_tokens": None}
    total = sum_efficiency([a, b, None])
    assert total["model_calls"] == 3
    assert total["input_tokens"] == 1  # the turn without a figure adds nothing
    only_null = {m: None for m in METRICS}
    assert sum_efficiency([only_null])["input_tokens"] is None
    assert sum_efficiency([None, None]) is None


# --- ledger mapping


CASE = Case(
    id="1-002",
    status="done",
    group="direct",
    query="Sao Paulo disturbance in H2 2024?",
    expected={"aoi_ids": "BRA.25_1", "dataset_id": "11"},
)


def _state(messages, aoi="BRA.25_1"):
    return {
        "aoi_selection": {
            "aois": [
                {
                    "src_id": aoi,
                    "name": aoi,
                    "subtype": "state-province",
                    "source": "gadm",
                }
            ]
        },
        "dataset": {
            "dataset_id": "11",
            "dataset_name": "x",
            "parameters": [],
            "context_layer": None,
        },
        "messages": messages,
        "charts_data": [],
        "codeact_parts": [],
        "statistics": [],
    }


def _patch_api(monkeypatch, states):
    """Serve each chat's state in turn, serialised like the real endpoint."""
    seen = {"chats": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/chat":
            seen["chats"] += 1
            return httpx.Response(
                200, text=json.dumps({"node": "agent", "update": "{}"})
            )
        if request.url.path.startswith("/api/threads/"):
            state = states[min(seen["chats"], len(states)) - 1]
            return httpx.Response(200, json={"state": dumps(state)})
        raise AssertionError(request.url)

    real_client = httpx.AsyncClient

    def fake_client(**kwargs):
        kwargs.pop("timeout", None)
        return real_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)


@pytest.mark.anyio
async def test_run_test_records_efficiency_without_changing_the_verdict(monkeypatch):
    _patch_api(monkeypatch, [_state(_turn(CASE.query, "short answer here"))])
    runner = APITestRunner(api_base_url="https://api.example", api_token="tok")
    result = await runner.run_test(CASE.query, case_to_expected(CASE))
    entry = result_to_entry(result, CASE.uid)
    assert entry["efficiency"]["model_calls"] == 2
    assert entry["efficiency"]["answer_words"] == 3
    assert entry["efficiency"]["input_tokens"] == 200
    assert "efficiency" not in entry["checks"]
    without = {k: v for k, v in entry.items() if k != "efficiency"}
    assert row_verdict(entry) == row_verdict(without)


def test_entry_without_efficiency_has_no_key():
    from goldset.eval_types import TestResult

    result = TestResult(
        thread_id="t", query="q", overall_score=0.0, execution_time="now"
    )
    assert "efficiency" not in result_to_entry(result, "u")


def test_merge_trials_keeps_per_trial_efficiency():
    eff = {m: 1 for m in METRICS}
    trials = [
        {
            "uid": "u",
            "id": "x",
            "checks": {"aoi_id_match": 1.0},
            "latency_s": 1.0,
            "efficiency": eff,
        },
        {"uid": "u", "id": "x", "checks": {"aoi_id_match": 1.0}, "latency_s": 2.0},
    ]
    merged = merge_trials(trials)
    assert merged["trials"][0]["efficiency"] == eff
    assert "efficiency" not in merged["trials"][1]


MT_TURNS = (
    {"query": "How much loss in Brazil?", "expected": {"aoi_ids": "BRA"}},
    {"query": "And Indonesia?", "expected": {"aoi_ids": "IDN"}},
)
MT_CASE = Case(id="mt-x", status="ready", group="multiturn", turns=MT_TURNS)


@pytest.mark.anyio
async def test_multiturn_sums_each_turn_once(monkeypatch):
    first = _turn("How much loss in Brazil?", "a b c")
    second = first + _turn("And Indonesia?", "d e f g h")
    _patch_api(monkeypatch, [_state(first, "BRA"), _state(second, "IDN")])
    runner = APITestRunner(api_base_url="https://api.example", api_token="tok")
    entry = await run_conversation(runner, MT_CASE, result_to_entry)
    # The second state holds both turns; the sum must not count turn 1 twice.
    assert entry["efficiency"]["model_calls"] == 4
    assert entry["efficiency"]["tool_calls"] == 2
    assert entry["efficiency"]["answer_words"] == 8
    assert entry["efficiency"]["input_tokens"] == 400
    assert [t["efficiency"]["model_calls"] for t in entry["turns_detail"]] == [2, 2]


def test_old_run_files_still_load():
    runs = sorted(Path(__file__).resolve().parents[1].glob("results/runs/*.json"))
    assert runs
    for path in runs:
        run = read_run(path)
        assert validate_run(run) == []
        assert all("efficiency" not in e for e in run["results"])


# --- the comparison report


def _load_report():
    path = Path(__file__).resolve().parents[1] / "tools" / "efficiency_report.py"
    spec = importlib.util.spec_from_file_location("efficiency_report", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


report = _load_report()


def _run(run_id, entries, **over):
    return {
        "run_id": run_id,
        "started": "2026-11-16T00:00:00Z",
        "environment": "staging",
        "build": "b",
        "ff": None,
        "harness": {"repo": "project-zeno", "sha": "x"},
        "judge_model": "j",
        "num_trials": 1,
        "caseset_version": "v",
        "results": entries,
        **over,
    }


def _entry(uid, latency, calls=None, **extra):
    entry = {
        "uid": uid,
        "id": uid,
        "checks": {"aoi_id_match": 1.0},
        "latency_s": latency,
    }
    if calls is not None:
        entry["efficiency"] = {m: None for m in METRICS} | {"model_calls": calls}
    return entry | extra


def test_percentile_interpolates():
    assert report.percentile([1, 2, 3, 4, 5], 50) == 3
    assert report.percentile([0, 10], 90) == 9
    assert report.percentile([7], 90) == 7


def test_case_value_uses_trial_median_and_skips_errors():
    entry = _entry(
        "u",
        99.0,
        trials=[
            {"checks": {}, "latency_s": 10.0},
            {"checks": {}, "latency_s": 30.0},
            {"checks": {}, "latency_s": 20.0},
        ],
    )
    assert report.case_value(entry, "latency_s") == 20.0
    assert report.case_value(_entry("u", 5.0, error="boom"), "latency_s") is None
    assert report.case_value(_entry("u", 5.0), "model_calls") is None


def test_report_pairs_shared_uids_and_counts_skipped():
    a = _run("A", [_entry("u1", 10.0, 4), _entry("u2", 20.0), _entry("only_a", 1.0, 1)])
    b = _run(
        "B", [_entry("u1", 5.0, 2), _entry("u2", 20.0, 3), _entry("only_b", 1.0, 1)]
    )
    stats = report.summarise(
        report._active(a), report._active(b), ["u1", "u2"], "model_calls"
    )
    assert stats["n"] == 1 and stats["skipped"] == 1
    assert (stats["median_a"], stats["median_b"]) == (4, 2)
    text = report.build_report(a, b, {"u1": "direct", "u2": "direct"})
    assert "Shared cases: 2 (only in A: 1, only in B: 1)" in text
    assert "| model_calls | 1 | 1 | 4.0 | 2.0 | -2.0 (-50%) |" in text
    assert "direct (2)" in text


def test_report_warns_when_runs_are_not_comparable():
    a = _run("A", [_entry("u1", 1.0)])
    b = _run("B", [_entry("u1", 1.0)], ff="concise")
    assert "WARNING: ff differs" in report.build_report(a, b, {})


def test_report_with_no_shared_cases():
    text = report.build_report(
        _run("A", [_entry("x", 1.0)]), _run("B", [_entry("y", 1.0)]), {}
    )
    assert "No shared cases." in text
