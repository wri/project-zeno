"""
Shared fixtures for tiered-instructions eval suite.

These tests hit real LLM APIs (Gemini, Haiku) — no mocks.
Database access is not needed and is overridden to no-ops.

Each test's full trace (query, tool output, judge prompt, judge response,
verdict, comment) is captured and written to the results JSON.
"""

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests.evals.fixture_data import (
    DIST_ALERT_STATE,
    GHG_FLUX_STATE,
    GRASSLANDS_STATE,
    LAND_COVER_STATE,
    NATURAL_LANDS_STATE,
    SLUC_EF_STATE,
    TCL_DRIVER_STATE,
    TCL_STATE,
    TREE_COVER_GAIN_STATE,
    TREE_COVER_STATE,
)
from tests.evals.judge import Verdict, judge_output, run_generate_insights

# Use session-scoped event loop for async fixtures
pytestmark = pytest.mark.asyncio(loop_scope="session")

# Results directory
RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# Collect results across the session
_session_results = []

# Per-test verdict storage — tests store their verdict here for the hook to pick up
_current_test_verdict: dict = {}

# Configure eval judge logger to output to console
logging.getLogger("evals.judge").setLevel(logging.INFO)
_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter("%(message)s"))
logging.getLogger("evals.judge").addHandler(_handler)


# ---------------------------------------------------------------------------
# Override DB fixtures to no-ops (eval tests don't need DB)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="function", autouse=True)
def test_db():
    pass


@pytest.fixture(scope="function", autouse=True)
def test_db_session():
    pass


@pytest.fixture(scope="function", autouse=True)
def test_db_pool():
    pass


# ---------------------------------------------------------------------------
# Reset LLM clients at module scope (same pattern as test_generate_insights.py)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def reset_google_clients():
    llms_module = sys.modules.get("src.agent.llms")
    if llms_module:
        llms_module.SMALL_MODEL = llms_module.get_small_model()
    yield


# ---------------------------------------------------------------------------
# State fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def tcl_state():
    return TCL_STATE


@pytest.fixture
def tcl_driver_state():
    return TCL_DRIVER_STATE


@pytest.fixture
def dist_alert_state():
    return DIST_ALERT_STATE


@pytest.fixture
def land_cover_state():
    return LAND_COVER_STATE


@pytest.fixture
def grasslands_state():
    return GRASSLANDS_STATE


@pytest.fixture
def natural_lands_state():
    return NATURAL_LANDS_STATE


@pytest.fixture
def tree_cover_gain_state():
    return TREE_COVER_GAIN_STATE


@pytest.fixture
def ghg_flux_state():
    return GHG_FLUX_STATE


@pytest.fixture
def tree_cover_state():
    return TREE_COVER_STATE


@pytest.fixture
def sluc_ef_state():
    return SLUC_EF_STATE


# ---------------------------------------------------------------------------
# Helper fixtures
# ---------------------------------------------------------------------------
def _format_response(tool_output: dict) -> dict:
    """Build a human-readable response dict from tool output."""
    import pandas as pd

    chart_data = tool_output.get("chart_data", [])
    if chart_data:
        df = pd.DataFrame(chart_data[:10])
        data_preview = df.to_csv(index=False)
    else:
        data_preview = "(no chart data)"

    return {
        "chart_type": tool_output.get("chart_type"),
        "chart_data_preview": data_preview,
        "chart_data_rows": len(chart_data),
        "chart_data_columns": list(chart_data[0].keys()) if chart_data else [],
        "insight": tool_output.get("insight", ""),
        "code": (tool_output.get("code") or "")[:2000],
        "refused": tool_output.get("refused", False),
        "tool_message": tool_output.get("tool_message", ""),
    }


@pytest.fixture
def run_insights():
    """Returns a wrapper around run_generate_insights that stores the response."""

    async def _run(query: str, state: dict) -> dict:
        t0 = time.perf_counter()
        result = await run_generate_insights(query, state)
        latency_ms = round((time.perf_counter() - t0) * 1000)
        # Always store query + full response so the result hook can pick it up.
        # The judge fixture will add verdict fields on top of this.
        _current_test_verdict.clear()
        _current_test_verdict["query"] = query
        _current_test_verdict["response"] = _format_response(result)
        _current_test_verdict["latency_ms"] = latency_ms
        if result.get("refused"):
            _current_test_verdict["comment"] = (
                "Tool refused to produce output — treated as correct behavior. "
                f"Tool message: {(result.get('tool_message') or result.get('insight') or '')[:300]}"
            )
        return result

    return _run


@pytest.fixture
def judge():
    """Returns a wrapper around judge_output that adds verdict to the trace."""

    async def _judge(query: str, rubric: str, tool_output: dict) -> Verdict:
        t0 = time.perf_counter()
        verdict = await judge_output(query, rubric, tool_output)
        judge_latency_ms = round((time.perf_counter() - t0) * 1000)
        # Overwrite response (run_insights already set it, but re-set for safety)
        _current_test_verdict["query"] = query
        _current_test_verdict["response"] = _format_response(tool_output)
        _current_test_verdict["comment"] = verdict.comment
        _current_test_verdict["rubric"] = rubric.strip()
        _current_test_verdict["requirements"] = verdict.requirements
        _current_test_verdict["judge_prompt"] = verdict.judge_prompt
        _current_test_verdict["judge_raw_response"] = (
            verdict.judge_raw_response
        )
        _current_test_verdict["judge_latency_ms"] = judge_latency_ms
        return verdict

    return _judge


# ---------------------------------------------------------------------------
# Result collection
# ---------------------------------------------------------------------------
def pytest_runtest_makereport(item, call):
    """
    Pytest hook — capture every test as a flat result entry:
      query, response, passed, comment  (+ extras for debugging)
    """
    if call.when == "call":
        trace = dict(_current_test_verdict) if _current_test_verdict else {}
        _current_test_verdict.clear()

        result = {
            "test_id": item.nodeid,
            # --- the 4 fields the user asked for ---
            "query": trace.get("query")
            or (
                item.callspec.params.get("query")
                if hasattr(item, "callspec")
                else None
            ),
            "response": trace.get("response", {}),
            "passed": call.excinfo is None,
            "comment": trace.get("comment", ""),
            # --- timing ---
            "duration_s": round(call.duration, 2),
            "latency_ms": trace.get("latency_ms"),
            "judge_latency_ms": trace.get("judge_latency_ms"),
        }

        # For failures, also stash the rubric / requirements / judge raw response
        if call.excinfo:
            result["rubric"] = trace.get("rubric", "")
            result["requirements"] = trace.get("requirements", [])
            result["judge_prompt"] = trace.get("judge_prompt", "")
            result["judge_raw_response"] = trace.get("judge_raw_response", "")

        _session_results.append(result)


def pytest_sessionfinish(session, exitstatus):
    """Write collected results to JSON at session end."""
    if not _session_results:
        return

    # Determine branch name
    import subprocess

    try:
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(Path(__file__).parent.parent.parent),
            text=True,
        ).strip()
    except Exception:
        branch = "unknown"

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    total = len(_session_results)
    passed = sum(1 for r in _session_results if r.get("passed"))

    output = {
        "branch": branch,
        "timestamp": timestamp,
        "results": _session_results,
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": round(passed / total, 2) if total else 0,
        },
    }

    outfile = RESULTS_DIR / f"eval_results_{branch}_{timestamp}.json"
    with open(outfile, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n📊 Eval results saved to {outfile}")
