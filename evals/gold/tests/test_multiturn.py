"""Multi-turn cases: identity, deltas, the store, and a full two-turn
conversation against a stateful mocked API."""

import json
from unittest.mock import AsyncMock

import httpx
import pytest

from goldset.canonical import conversation_uid
from goldset.cli import result_to_entry
from goldset.runner.api import TRANSIENT_CHAT_RETRIES, APITestRunner
from goldset.runner.multiturn import (
    evaluate_deltas,
    flatten_turn_checks,
    run_conversation,
)
from goldset.store import Case, read_case, write_case

TURNS = (
    {
        "query": "How much tree cover loss did Brazil have in 2022?",
        "expected": {"aoi_ids": "BRA", "dataset_id": "4"},
    },
    {
        "query": "And for Indonesia?",
        "expected": {"aoi_ids": "IDN"},
        "deltas": {"changed": ["aoi_ids"], "retain": ["dataset_id"]},
    },
)

CASE = Case(id="mt-x", status="ready", group="multiturn", turns=TURNS)


# --- identity


def test_conversation_uid_is_order_sensitive():
    reordered = (TURNS[1], TURNS[0])
    assert conversation_uid(TURNS) != conversation_uid(reordered)


def test_conversation_uid_ignores_deltas_and_metadata():
    without_deltas = (
        TURNS[0],
        {"query": TURNS[1]["query"], "expected": TURNS[1]["expected"]},
    )
    assert conversation_uid(TURNS) == conversation_uid(without_deltas)
    changed = (TURNS[0], {**TURNS[1], "expected": {"aoi_ids": "MYS"}})
    assert conversation_uid(TURNS) != conversation_uid(changed)


def test_conversation_uid_with_deltas_mints_on_delta_edits():
    """The v2 rule (uid_includes_deltas): a scored delta assertion is test
    content, so editing one mints a new version."""
    base = conversation_uid(TURNS, include_deltas=True)
    assert base != conversation_uid(TURNS)  # deltas now participate
    edited = (TURNS[0], {**TURNS[1], "deltas": {"changed": ["aoi_ids"]}})
    assert conversation_uid(edited, include_deltas=True) != base
    swapped_kind = (
        TURNS[0],
        {**TURNS[1], "deltas": {"changed": ["aoi_ids"], "absent": ["dataset_id"]}},
    )
    assert conversation_uid(swapped_kind, include_deltas=True) != base
    added_field = (
        TURNS[0],
        {
            **TURNS[1],
            "deltas": {"changed": ["aoi_ids", "start_date"], "retain": ["dataset_id"]},
        },
    )
    assert conversation_uid(added_field, include_deltas=True) != base


def test_conversation_uid_with_deltas_ignores_delta_key_and_list_order():
    turns = (
        TURNS[0],
        {
            **TURNS[1],
            "deltas": {
                "changed": ["aoi_ids", "start_date"],
                "retain": ["dataset_id", "context_layer"],
            },
        },
    )
    reordered = (
        TURNS[0],
        {
            **TURNS[1],
            "deltas": {
                "retain": ["context_layer", "dataset_id"],
                "changed": ["start_date", "aoi_ids"],
            },
        },
    )
    assert conversation_uid(turns, include_deltas=True) == conversation_uid(
        reordered, include_deltas=True
    )


def test_conversation_uid_with_deltas_ignores_empty_deltas():
    """Only non-empty deltas participate: a turn with none, ``{}``, or only
    empty lists hashes as it would without the flag."""
    no_deltas = (
        TURNS[0],
        {"query": TURNS[1]["query"], "expected": TURNS[1]["expected"]},
    )
    empty = (TURNS[0], {**no_deltas[1], "deltas": {}})
    empty_lists = (TURNS[0], {**no_deltas[1], "deltas": {"changed": [], "retain": []}})
    expected_uid = conversation_uid(no_deltas)
    for turns in (no_deltas, empty, empty_lists):
        assert conversation_uid(turns, include_deltas=True) == expected_uid


# --- store


def test_multiturn_round_trip(tmp_path):
    path = write_case(tmp_path, CASE)
    loaded, stored_uid = read_case(path)
    assert loaded == CASE
    assert stored_uid == CASE.uid
    assert loaded.is_multiturn


def test_multiturn_validation():
    with_query = Case(id="x", status="ready", group="g", query="q", turns=TURNS)
    assert any("must not set query" in p for p in with_query.validate())
    one_turn = Case(id="x", status="ready", group="g", turns=(TURNS[0],))
    assert any("at least 2 turns" in p for p in one_turn.validate())
    turn1_deltas = Case(
        id="x",
        status="ready",
        group="g",
        turns=({**TURNS[0], "deltas": {"changed": ["aoi_ids"]}}, TURNS[1]),
    )
    assert any("turn 1 cannot assert deltas" in p for p in turn1_deltas.validate())


def test_typoed_delta_field_fails_authoring_validation():
    """A typo'd snapshot field (aoi_id vs aoi_ids) must fail at authoring
    time: a silently-abstaining delta check is a coverage hole."""
    typo = Case(
        id="x",
        status="ready",
        group="g",
        turns=(TURNS[0], {**TURNS[1], "deltas": {"changed": ["aoi_id"]}}),
    )
    assert any("unknown fields ['aoi_id']" in p for p in typo.validate())
    # the correctly spelled field still validates
    assert not Case(id="x", status="ready", group="g", turns=TURNS).validate()


# --- deltas


def test_delta_assertions():
    prev = {"aoi_ids": "BRA", "dataset_id": "4", "context_layer": "primary_forest"}
    cur = {"aoi_ids": "IDN", "dataset_id": "4", "context_layer": ""}
    ok = evaluate_deltas(
        prev,
        cur,
        {"changed": ["aoi_ids"], "retain": ["dataset_id"], "absent": ["context_layer"]},
    )
    assert ok["state_delta_score"] == 1.0

    stale = evaluate_deltas(prev, {**cur, "aoi_ids": "BRA"}, {"changed": ["aoi_ids"]})
    assert stale["state_delta_score"] == 0.0
    assert "should have changed" in stale["state_delta_reason"]

    lost = evaluate_deltas(prev, {**cur, "dataset_id": "0"}, {"retain": ["dataset_id"]})
    assert lost["state_delta_score"] == 0.0

    leak = evaluate_deltas(
        prev, {**cur, "context_layer": "primary_forest"}, {"absent": ["context_layer"]}
    )
    assert "contamination" in leak["state_delta_reason"]

    # Defence-in-depth for direct callers only: the schema enum and
    # Case.validate() reject unknown fields at authoring time, so a stored
    # case can never reach this abstain path.
    unknown = evaluate_deltas(prev, cur, {"changed": ["not_a_field"]})
    assert unknown["state_delta_score"] is None


def test_flatten_turn_checks():
    flat = flatten_turn_checks(
        [
            {"checks": {"aoi_id_match": 1.0}},
            {"checks": {"aoi_id_match": 0.0, "state_delta": 1.0}},
        ]
    )
    assert flat == {
        "t1.aoi_id_match": 1.0,
        "t2.aoi_id_match": 0.0,
        "t2.state_delta": 1.0,
    }


def test_turn_prefixed_checks_resolve_buckets_and_verdicts():
    from goldset.buckets import buckets_for, row_verdict

    assert buckets_for("t2.aoi_id_match") == ("retrieval",)
    assert buckets_for("t1.state_delta") == ("retrieval",)
    assert (
        row_verdict({"checks": {"t1.aoi_id_match": 1.0, "t2.state_delta": 0.0}})
        == "fail"
    )
    assert row_verdict({"checks": {"t1.date_coverage": 0.0}}) == "uncovered"


# --- the conversation loop, end to end against a stateful mock


def _state(aoi, dataset):
    return {
        "aoi_selection": {
            "aois": [
                {"src_id": aoi, "name": aoi, "subtype": "country", "source": "gadm"}
            ]
        },
        "dataset": {
            "dataset_id": dataset,
            "dataset_name": "TCL",
            "parameters": [],
            "context_layer": None,
        },
        "messages": [],
        "charts_data": [],
        "codeact_parts": [],
        "statistics": [
            {
                "source_url": "https://api/x",
                "id": "p1",
                "data": [{"year": 2022, "area_ha": 1.0}],
            }
        ],
    }


@pytest.fixture
def stateful_transport(monkeypatch):
    seen = {"chats": 0, "thread_ids": set()}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/chat":
            seen["chats"] += 1
            seen["thread_ids"].add(json.loads(request.content)["thread_id"])
            return httpx.Response(
                200,
                text=json.dumps(
                    {
                        "node": "trace_info",
                        "update": json.dumps(
                            {"trace_id": "t", "trace_url": "https://lf/t"}
                        ),
                    }
                ),
            )
        if request.url.path.startswith("/api/threads/"):
            state = _state("BRA", "4") if seen["chats"] == 1 else _state("IDN", "4")
            return httpx.Response(200, json={"state": json.dumps(state)})
        raise AssertionError(request.url)

    real_client = httpx.AsyncClient

    def fake_client(**kwargs):
        kwargs.pop("timeout", None)
        return real_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    return seen


@pytest.mark.anyio
async def test_two_turn_conversation(stateful_transport):
    runner = APITestRunner(api_base_url="https://api.example", api_token="tok")
    entry = await run_conversation(runner, CASE, result_to_entry)

    # one thread, two POSTs: the continuation mechanism
    assert stateful_transport["chats"] == 2
    assert len(stateful_transport["thread_ids"]) == 1

    checks = entry["checks"]
    assert checks["t1.aoi_id_match"] == 1.0  # BRA as expected
    assert checks["t2.aoi_id_match"] == 1.0  # IDN as expected
    assert checks["t2.state_delta"] == 1.0  # aoi changed, dataset retained
    assert entry["uid"] == CASE.uid
    assert len(entry["turns_detail"]) == 2


# --- abort on turn failure


@pytest.fixture
def first_turn_fails_transport(monkeypatch):
    seen = {"chats": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/chat":
            seen["chats"] += 1
            return httpx.Response(500, text="backend exploded")
        if request.url.path.startswith("/api/threads/"):
            return httpx.Response(200, json={"state": json.dumps(_state("BRA", "4"))})
        raise AssertionError(request.url)

    real_client = httpx.AsyncClient

    def fake_client(**kwargs):
        kwargs.pop("timeout", None)
        return real_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    monkeypatch.setattr("goldset.runner.api.anyio.sleep", AsyncMock())
    return seen


@pytest.mark.anyio
async def test_errored_turn_aborts_conversation(first_turn_fails_transport):
    """If turn N errors, turn N+1 must never fire: it would race a
    possibly-still-processing backend and diff against an empty snapshot.
    The un-run turns contribute no checks at all."""
    runner = APITestRunner(api_base_url="https://api.example", api_token="tok")
    entry = await run_conversation(runner, CASE, result_to_entry)

    # turn 1 exhausts its transient-5xx retries before erroring; turn 2 never sent
    assert first_turn_fails_transport["chats"] == TRANSIENT_CHAT_RETRIES + 1
    assert entry["error"].startswith("t1:")
    assert not any(name.startswith("t2.") for name in entry["checks"])
    assert "t2.state_delta" not in entry["checks"]
    assert len(entry["turns_detail"]) == 1


@pytest.mark.anyio
async def test_delta_exception_degrades_turn_not_run(stateful_transport, monkeypatch):
    """An unexpected exception in delta code must degrade the turn to an
    error state (mirroring run_test's own degradation), never propagate:
    run_cases gathers without return_exceptions."""

    def boom(previous, current, deltas):
        raise RuntimeError("snapshot diff bug")

    monkeypatch.setattr("goldset.runner.multiturn.evaluate_deltas", boom)
    runner = APITestRunner(api_base_url="https://api.example", api_token="tok")
    entry = await run_conversation(runner, CASE, result_to_entry)

    # turn 1 has no deltas, so only turn 2 trips the guard, after both ran
    assert stateful_transport["chats"] == 2
    assert entry["error"] == "t2: delta evaluation failed: snapshot diff bug"
    assert "t2.state_delta" not in entry["checks"]


# --- snapshots see actuals even on turns without that expectation


def test_snapshot_fields_extracted_without_expectations():
    """suggested_datasets/nudge actuals must be extracted even when the turn
    carries no such expectation (scores still abstain), or later delta
    assertions on those fields would silently diff empty snapshots."""
    from goldset.eval_types import TestResult
    from goldset.evaluators.nudge_evaluator import evaluate_nudge
    from goldset.evaluators.suggested_datasets_evaluator import (
        evaluate_suggested_datasets,
    )
    from goldset.runner.multiturn import state_snapshot

    state = {
        "suggested_datasets": [{"dataset_id": "4"}, {"dataset_id": "11"}],
        "nudge": {"type": "aoi_choice", "options": ["Puri, Odisha, India"]},
    }
    evaluations = {
        **evaluate_suggested_datasets(state, None),
        **evaluate_nudge(state, None, None),
    }
    assert evaluations["suggested_datasets_match_score"] is None
    assert evaluations["nudge_match_score"] is None

    result = TestResult(
        thread_id="t",
        query="q",
        overall_score=0.0,
        execution_time="now",
        **evaluations,
    )
    snapshot = state_snapshot(result)
    assert snapshot["suggested_datasets"] == "4; 11"
    assert snapshot["nudge_type"] == "aoi_choice"


# --- the CLI ships this exact code path


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])  # run_cases is asyncio-only
async def test_cli_dispatches_conversations_to_run_conversation(
    anyio_backend, monkeypatch, tmp_path
):
    """cli.run_cases must delegate multi-turn cases to the unit-tested
    runner.multiturn.run_conversation, not an inline reimplementation."""
    import argparse

    from goldset.cli import run_cases

    calls = []

    async def fake_run_conversation(
        runner, case, result_to_entry, artifact_sink_factory=None
    ):
        calls.append((case.id, result_to_entry.__name__))
        assert artifact_sink_factory is not None
        return {"uid": case.uid, "id": case.id, "checks": {"t1.aoi_id_match": 1.0}}

    monkeypatch.setattr(
        "goldset.runner.multiturn.run_conversation", fake_run_conversation
    )
    args = argparse.Namespace(
        resolved_url="https://api.example",
        api_token="tok",
        ff=None,
        verbose=False,
        results_dir=tmp_path,
        run_id="r1",
        workers=1,
        trials=1,
        slow_threshold=180.0,
        trial_timeout=900.0,
        # main() always sets this before run_cases; empty means no
        # ground-truth case in the run, which is true of every multi-turn one.
        ground_truth={},
    )
    entries = await run_cases(args, [CASE])
    assert calls == [("mt-x", "result_to_entry")]
    assert entries[0]["checks"] == {"t1.aoi_id_match": 1.0}


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])  # run_cases is asyncio-only
async def test_progress_counter_reaches_total_regardless_of_completion_order(
    anyio_backend, monkeypatch, tmp_path, capsys
):
    """Each stdout progress line ends with (completed/total); concurrent
    cases can finish out of input order, so the count must track completion
    order, not case order, and must land on N/N exactly once."""
    import argparse
    import asyncio

    from goldset.cli import run_cases
    from goldset.store import Case

    cases = [
        Case(id=f"mt-{n}", status="ready", group="multiturn", turns=TURNS)
        for n in range(3)
    ]

    async def fake_run_conversation(
        runner, case, result_to_entry, artifact_sink_factory=None
    ):
        # reverse-order delay: mt-2 finishes first, mt-0 finishes last,
        # the opposite of input order, to prove the counter isn't just
        # echoing each case's position in `cases`.
        await asyncio.sleep(0.03 * (2 - int(case.id.split("-")[1])))
        return {"uid": case.uid, "id": case.id, "checks": {"t1.aoi_id_match": 1.0}}

    monkeypatch.setattr(
        "goldset.runner.multiturn.run_conversation", fake_run_conversation
    )
    args = argparse.Namespace(
        resolved_url="https://api.example",
        api_token="tok",
        ff=None,
        verbose=False,
        results_dir=tmp_path,
        run_id="r1",
        workers=3,
        trials=1,
        slow_threshold=180.0,
        trial_timeout=900.0,
        ground_truth={},
    )
    await run_cases(args, cases)
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(lines) == 3
    counts = [line.rsplit("(", 1)[1].rstrip(")") for line in lines]
    assert sorted(counts) == ["1/3", "2/3", "3/3"]
    # mt-2 was scheduled to finish first
    assert lines[0].startswith("  mt-2 ") and lines[0].endswith("(1/3)")
    assert lines[-1].endswith("(3/3)")
