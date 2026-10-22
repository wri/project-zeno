"""End-to-end runner test against a mocked API: no network, no judge.

Covers: streamed chat POST, trace capture, state fetch, evaluation via the
registry, artefact capture, and the CLI's result->ledger-entry mapping.
"""

import gzip
import json
import time
from types import SimpleNamespace

import anyio
import httpx
import pytest

from goldset.adapter import case_to_expected
from goldset.cli import merge_trials, result_to_entry
from goldset.runner.api import APITestRunner
from goldset.store import Case

CASE = Case(
    id="1-002",
    status="done",
    group="direct",
    query="Sao Paulo disturbance in H2 2024?",
    expected={"aoi_ids": "BRA.25_1", "dataset_id": "11"},
)

STATE = {
    "aoi_selection": {
        "aois": [
            {
                "src_id": "BRA.25_1",
                "name": "São Paulo",
                "subtype": "state-province",
                "source": "gadm",
            }
        ]
    },
    "dataset": {
        "dataset_id": "11",
        "dataset_name": "Integrated alerts",
        "parameters": [],
        "context_layer": None,
    },
    "messages": [],
    "charts_data": [],
    "codeact_parts": [],
    "statistics": [
        {
            "source_url": "https://api.example/x",
            "id": "pull-1",
            "data": [{"year": 2024, "area_ha": 1.0}],
            "start_date": "2024-07-01",
            "end_date": "2024-12-31",
        }
    ],
}


def transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/chat":
            lines = [
                json.dumps(
                    {
                        "node": "trace_info",
                        "update": json.dumps(
                            {"trace_id": "t-1", "trace_url": "https://lf/t-1"}
                        ),
                    }
                ),
                json.dumps({"node": "agent", "update": "{}"}),
            ]
            return httpx.Response(200, text="\n".join(lines))
        if request.url.path.startswith("/api/threads/"):
            # the real endpoint returns state as a serialised JSON string
            return httpx.Response(200, json={"state": json.dumps(STATE)})
        raise AssertionError(f"unexpected request: {request.url}")

    return httpx.MockTransport(handler)


@pytest.fixture
def patched_client(monkeypatch):
    real_client = httpx.AsyncClient

    def fake_client(**kwargs):
        kwargs.pop("timeout", None)
        return real_client(transport=transport())

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)


async def _run(tmp_path):
    captured = {}
    runner = APITestRunner(api_base_url="https://api.example", api_token="tok")
    result = await runner.run_test(
        CASE.query,
        case_to_expected(CASE),
        artifact_sink=lambda a: captured.update(a),
    )
    return result, captured


@pytest.mark.anyio
async def test_run_test_scores_and_captures(patched_client, tmp_path):
    result, artifact = await _run(tmp_path)
    assert result.trace_url == "https://lf/t-1"
    assert result.aoi_id_match_score == 1.0
    assert result.dataset_id_match_score == 1.0
    assert result.error is None
    assert result.overall_score == 1.0
    # extras flow through: uid arrived on the TestResult
    assert result.model_dump()["uid"] == CASE.uid
    # the artefact keeps raw agent signals that a run record does not
    assert artifact["statistics_last"]["data_rows_total"] == 1
    assert artifact["dataset"]["dataset_id"] == "11"


@pytest.mark.anyio
async def test_result_maps_to_ledger_entry(patched_client, tmp_path):
    result, _ = await _run(tmp_path)
    entry = result_to_entry(result, CASE.uid)
    assert entry["uid"] == CASE.uid
    assert entry["id"] == "1-002"
    assert entry["checks"]["aoi_id_match"] == 1.0
    assert entry["checks"]["nudge_match"] is None
    assert "overall" not in entry["checks"]
    assert entry["latency_s"] is not None


def test_run_record_names_its_caseset():
    """A run must say which store it loaded, not just the content hash:
    caseset_version alone can't tell a reader v1 from v2 without git
    archaeology over the manifests."""
    import argparse

    from goldset.cli import build_run_record
    from goldset.ledger import validate_run

    args = argparse.Namespace(
        run_id="20260804T120000Z_staging_experimental",
        build="b",
        ff="experimental",
        trials=3,
        workers=10,
        trial_timeout=900.0,
        note=None,
        cases_dir=__import__("pathlib").Path("cases/v2"),
    )
    entries = [{"uid": "u1", "id": "1-001", "checks": {"aoi_id_match": 1.0}}]
    record = build_run_record(
        args,
        {"caseset_version": "2276185a231bfdad"},
        entries,
        started="2026-08-04T12:00:00Z",
        environment="staging",
    )
    assert record["caseset"] == "v2"
    assert record["caseset_version"] == "2276185a231bfdad"
    assert validate_run(record) == []
    # A run with no ground-truth entries gains no key at all
    assert "ground_truth" not in record


def test_run_record_carries_the_ground_truth_block_from_its_entries():
    """Keyed on the entries, not args.ground_truth: a resume's args hold only
    the remaining cases, which here carry none."""
    import argparse

    from goldset.cli import build_run_record

    args = argparse.Namespace(
        run_id="20260914T120000Z_staging",
        build="b",
        ff=None,
        trials=1,
        workers=10,
        trial_timeout=900.0,
        note=None,
        cases_dir=__import__("pathlib").Path("cases/v2"),
        ground_truth={},
        analytics_base_url="https://analytics.example",
        prefetch_seconds=3.4,
    )
    entries = [
        {"uid": "u1", "id": "1-046", "checks": {}, "ground_truth": {"values": [1.0]}},
        {"uid": "u2", "id": "1-002", "checks": {}},
    ]
    record = build_run_record(
        args,
        {"caseset_version": "c"},
        entries,
        started="2026-09-14T12:00:00Z",
        environment="staging",
    )
    assert record["ground_truth"] == {
        "base_url": "https://analytics.example",
        "cases": 1,
        "prefetch_seconds": 3.4,
        "tolerance": 0.02,
    }


def test_run_cases_records_the_agent_figure_for_every_trial(monkeypatch, tmp_path):
    """The ground-truth record carries each trial's figure, aligned with `trials`,
    so diff_runs can examine exactly the trials that failed."""
    import argparse
    import asyncio

    import goldset.runner.api
    from goldset import cli
    from goldset.eval_types import TestResult

    figures = iter([[658496.56], [12.0]])

    class FakeRunner:
        def __init__(self, **kwargs):
            pass

        async def run_test(self, query, expected, artifact_sink=None):
            return TestResult(
                thread_id="t",
                query=query,
                overall_score=0.0,
                execution_time="now",
                test_id=expected.test_id,
                ground_truth_match_score=1.0,
                agent_ground_truth_values=next(figures),
            )

    monkeypatch.setattr(goldset.runner.api, "APITestRunner", FakeRunner)
    ground_truth = SimpleNamespace(
        values=[658496.56],
        unresolved=None,
        to_ledger=lambda: {"values": [658496.56], "digest": "d"},
    )
    args = argparse.Namespace(
        resolved_url="https://api.test",
        api_token="t",
        ff=None,
        verbose=False,
        trial_timeout=60.0,
        ground_truth={GT_CASE.uid: ground_truth},
        results_dir=tmp_path,
        run_id="20260915T000000Z_staging",
        workers=1,
        trials=2,
        slow_threshold=180.0,
    )
    # asyncio.run, not the anyio marker: run_cases uses asyncio primitives,
    # exactly as `gold run` drives it.
    [entry] = asyncio.run(cli.run_cases(args, [GT_CASE]))
    assert entry["ground_truth"]["agent_values"] == [[658496.56], [12.0]]
    assert entry["ground_truth"]["digest"] == "d"
    assert len(entry["trials"]) == 2


def test_run_record_names_selected_judge_backend():
    import argparse

    from goldset.cli import build_run_record

    args = argparse.Namespace(
        run_id="20260804T120000Z_staging_experimental",
        build="b",
        ff="experimental",
        trials=1,
        workers=10,
        trial_timeout=900.0,
        note=None,
        cases_dir=__import__("pathlib").Path("cases/v2"),
        judge_backend="openrouter-jev-decisions",
    )
    entries = [{"uid": "u1", "id": "1-001", "checks": {"aoi_id_match": 1.0}}]
    record = build_run_record(
        args,
        {"caseset_version": "2276185a231bfdad"},
        entries,
        started="2026-08-04T12:00:00Z",
        environment="staging",
    )
    assert record["judge_model"] == "typesafe/jev-1.13"


def test_merge_trials_majority_and_detail():
    trials = [
        {"uid": "u", "id": "1-002", "checks": {"aoi_id_match": 1.0}, "latency_s": 1.0},
        {"uid": "u", "id": "1-002", "checks": {"aoi_id_match": 0.0}, "latency_s": 2.0},
        {"uid": "u", "id": "1-002", "checks": {"aoi_id_match": 1.0}, "latency_s": 3.0},
    ]
    merged = merge_trials(trials)
    assert merged["checks"]["aoi_id_match"] == 1.0
    assert [t["latency_s"] for t in merged["trials"]] == [1.0, 2.0, 3.0]
    assert merge_trials(trials[:1]) == trials[0]


def test_artifact_writer_round_trip(tmp_path):
    from goldset.runner.artifacts import ArtifactWriter

    writer = ArtifactWriter(tmp_path, "run-x")
    path = writer("abc123", 1, {"tool_calls": [], "charts_data": None})
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        assert json.load(handle)["tool_calls"] == []
    assert path.name == "abc123.json.gz"
    assert writer("abc123", 2, {}).name == "abc123_t2.json.gz"


def test_failed_checks_carry_their_actuals():
    """Expected-vs-measured in reports needs the measured side recorded:
    on failures only, trimmed, absent when nothing failed."""
    from goldset.eval_types import TestResult

    result = TestResult(
        thread_id="t",
        query="q",
        overall_score=0.0,
        execution_time="now",
        test_id="1-002",
        aoi_id_match_score=0.0,
        actual_id="XYZ.9_1",
        agent_answer_score=0.0,
        actual_agent_answer="A" * 900,
        dataset_id_match_score=1.0,
        actual_dataset_id="4",
    )
    entry = result_to_entry(result, "u")
    assert entry["actuals"]["aoi_id_match"] == "XYZ.9_1"
    assert len(entry["actuals"]["agent_answer"]) == 300  # trimmed
    assert "dataset_id_match" not in entry["actuals"]  # passed: not recorded


class _KeepaliveStream(httpx.AsyncByteStream):
    """A stream that never finishes but keeps every per-read timeout happy:
    the exact staging failure mode of 2026-08-01."""

    async def __aiter__(self):
        yield b'{"node": "keepalive"}\n'
        while True:
            await anyio.sleep(0.02)
            yield b"\n"


class _HangingTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_KeepaliveStream(), request=request)


@pytest.mark.anyio
async def test_wall_clock_limit_bounds_a_keepalive_stream(monkeypatch):
    """The per-read HTTP timeout resets on every keepalive; only the
    wall-clock limit can end such a trial, as an error row, quickly."""
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=_HangingTransport()),
    )
    runner = APITestRunner(
        api_base_url="https://api.example",
        api_token="tok",
        wall_clock_limit=0.3,
    )
    start = time.monotonic()
    result = await runner.run_test(CASE.query, case_to_expected(CASE))
    assert time.monotonic() - start < 5.0
    assert "wall-clock" in (result.error or "")
    assert result.aoi_id_match_score is None


# ---------------------------------------------------------------------------
# Reading the agent's own pulled table (ground-truth runs only).


def _patched(mock_transport):
    """A fake httpx.AsyncClient bound to `mock_transport`, matching the
    `patched_client` fixture above but parameterised per test."""
    real_client = httpx.AsyncClient

    def fake_client(**kwargs):
        kwargs.pop("timeout", None)
        return real_client(transport=mock_transport)

    return fake_client


GT_CASE = Case(
    id="1-046",
    status="done",
    group="direct",
    query="CO2 in Ihorombe 2019?",
    expected={
        "aoi_ids": "MDG.3.4_1",
        "aoi_source": "gadm",
        "dataset_id": "4",
        "ground_truth": "sum(carbon_emissions_MgCO2e)",
    },
)
PULLED = {"tree_cover_loss_year": [2019], "carbon_emissions_MgCO2e": [658496.56]}
PULL_URL = "http://analytics.example/v0/land_change/tree_cover_loss/analytics/abc"


def _gt_expected(values=(658496.56,), unresolved=None):
    """The adapter reads only `values` and `unresolved` off a GroundTruth."""
    return case_to_expected(
        GT_CASE, SimpleNamespace(values=list(values), unresolved=unresolved)
    )


def _state_with_pull() -> dict:
    return {**STATE, "statistics": [{"source_url": PULL_URL, "id": "p1", "data": {}}]}


def transport_with_pull(pull_response=None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/chat":
            return httpx.Response(
                200, text=json.dumps({"node": "agent", "update": "{}"})
            )
        if request.url.path.startswith("/api/threads/"):
            return httpx.Response(200, json={"state": json.dumps(_state_with_pull())})
        if str(request.url) == PULL_URL:
            return pull_response or httpx.Response(
                200, json={"data": {"result": PULLED}}
            )
        raise AssertionError(f"unexpected request: {request.url}")

    return httpx.MockTransport(handler)


@pytest.mark.anyio
async def test_pulled_data_is_read_for_a_ground_truth_case(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _patched(transport_with_pull()))
    runner = APITestRunner(api_base_url="https://api.test", analytics_token="t")
    captured: dict = {}
    result = await runner.run_test(
        GT_CASE.query, _gt_expected(), artifact_sink=captured.update
    )
    assert captured["pulled_data"]["carbon_emissions_MgCO2e"] == [658496.56]
    assert captured["pulled_data"]["_rows_total"] == 1
    # ...and grades it: the agent's pull yields the fetched value.
    entry = result_to_entry(result, GT_CASE.uid)
    assert entry["checks"]["ground_truth_match"] == 1.0
    assert "error" not in entry


@pytest.mark.anyio
async def test_an_unresolved_selector_errors_the_row(monkeypatch):
    from goldset.buckets import row_verdict

    monkeypatch.setattr(httpx, "AsyncClient", _patched(transport_with_pull()))
    runner = APITestRunner(api_base_url="https://api.test", analytics_token="t")
    result = await runner.run_test(
        GT_CASE.query,
        _gt_expected(values=(), unresolved="column 'x' not in the response"),
    )
    entry = result_to_entry(result, GT_CASE.uid)
    assert entry["error"] == "ground truth unresolved: column 'x' not in the response"
    assert entry["checks"]["ground_truth_match"] is None
    assert row_verdict(entry) == "error"


@pytest.mark.anyio
async def test_a_failed_pull_read_degrades_instead_of_failing_the_trial(monkeypatch):
    """Enrichment, not a verdict: a 404 here must not kill the row."""
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        _patched(transport_with_pull(httpx.Response(404, json={}))),
    )
    runner = APITestRunner(api_base_url="https://api.test", analytics_token="t")
    captured: dict = {}
    result = await runner.run_test(
        GT_CASE.query, _gt_expected(), artifact_sink=captured.update
    )
    assert result.error is None
    assert captured["pulled_data"] is None
    # unreadable pull, no chart: cannot tell agent from harness
    assert result.ground_truth_match_score is None


@pytest.mark.anyio
async def test_no_pull_read_without_ground_truth(monkeypatch):
    """A case with no selector must not issue the extra request."""

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == PULL_URL:
            raise AssertionError("must not read the pull for a non-GT case")
        if request.url.path == "/api/chat":
            return httpx.Response(
                200, text=json.dumps({"node": "agent", "update": "{}"})
            )
        return httpx.Response(200, json={"state": json.dumps(_state_with_pull())})

    monkeypatch.setattr(httpx, "AsyncClient", _patched(httpx.MockTransport(handler)))
    runner = APITestRunner(api_base_url="https://api.test", analytics_token="t")
    captured: dict = {}
    await runner.run_test(
        CASE.query, case_to_expected(CASE), artifact_sink=captured.update
    )
    assert captured["pulled_data"] is None


def test_sectioned_pulled_data_is_capped_per_section():
    """LGMS (12) answers {section: {column: [values]}} where every other dataset
    answers flat. Seen live 2026-09-08; a flat cap left it uncapped."""
    from goldset.runner.artifacts import STATISTICS_ROW_LIMIT, _pulled_data

    sectioned = {
        "vegetation": {"aoi_id": ["A"] * 300, "net_flux_MgCO2e": [1.0] * 300},
        "organic_soil": {"aoi_id": [], "area_ha": []},
    }
    got = _pulled_data({"pulled_data": sectioned})
    assert len(got["vegetation"]["aoi_id"]) == STATISTICS_ROW_LIMIT
    assert got["vegetation"]["_rows_total"] == 300
    assert got["organic_soil"]["_rows_total"] == 0

    flat = {"tree_cover_loss_year": [2019] * 300, "area_ha": [1.0] * 300}
    got = _pulled_data({"pulled_data": flat})
    assert len(got["area_ha"]) == STATISTICS_ROW_LIMIT
    assert got["_rows_total"] == 300

    assert _pulled_data({}) is None
    assert _pulled_data({"pulled_data": None}) is None
