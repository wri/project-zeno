"""Harness tests. Exercises the full tool pipeline, artifact lifecycle,
and session context using in-memory Store (no LLM, no DB)."""

import pytest

from langchain.tools import ToolRuntime
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from src.agent.harness.artifact import Artifact
from src.agent.harness.middleware import _format_session_block
from src.agent.harness.subagents.analyst import analyst_subagent
from src.agent.harness.subagents.geo import geo_subagent
from src.agent.harness.tools.fetch import fetch
from src.agent.harness.tools.update_artifact import update_artifact


def _make_runtime(store=None, call_id="test_call"):
    store = store or InMemoryStore()
    events = []
    rt = ToolRuntime(
        state={},
        context={},
        config={},
        stream_writer=lambda e: events.append(e),
        tool_call_id=call_id,
        store=store,
    )
    return rt, store, events


@pytest.mark.asyncio
async def test_full_pipeline():
    """geo -> fetch -> analyst: end-to-end pipeline producing an artifact."""
    store = InMemoryStore()
    rt, _, events = _make_runtime(store=store)

    geo_result = await geo_subagent.ainvoke({"query": "Para", "runtime": rt})
    assert isinstance(geo_result, Command)
    refs = geo_result.update["aoi_refs"]
    assert refs[0]["src_id"] == "BRA.14_1"

    fetch_result = await fetch.ainvoke({
        "aoi_refs": refs,
        "dataset_id": "tree_cover_loss",
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
        "runtime": rt,
    })
    stat_id = fetch_result.update["data_refs"][0]
    assert await store.aget(("data",), stat_id) is not None

    art_result = await analyst_subagent.ainvoke({
        "task": "bar chart of drivers",
        "stat_ids": [stat_id],
        "dataset_id": "tree_cover_loss",
        "aoi_refs": refs,
        "runtime": rt,
    })
    art_id = art_result.update["artifact_ids"][0]
    saved = await store.aget(("artifacts",), art_id)
    assert saved.value["type"] == "chart"
    assert saved.value["content"]["data"]

    event_types = [e["type"] for e in events]
    assert "aoi_resolved" in event_types
    assert "data_fetched" in event_types
    assert "artifact" in event_types


@pytest.mark.asyncio
async def test_artifact_edit_lineage():
    """update_artifact creates a child with parent_id linkage."""
    store = InMemoryStore()
    original = Artifact(
        type="chart", title="Original",
        content={"spec": {"mark": "bar"}, "data": [{"x": 1}]},
    )
    await store.aput(("artifacts",), original.id, original.to_dict())
    rt, _, events = _make_runtime(store=store)

    result = await update_artifact.ainvoke({
        "artifact_id": original.id,
        "changes": {"chart_type": "line", "title": "Renamed"},
        "runtime": rt,
    })
    new_id = result.update["artifact_ids"][0]
    child = await store.aget(("artifacts",), new_id)
    assert child.value["parent_id"] == original.id
    assert child.value["title"] == "Renamed"
    assert child.value["content"]["spec"]["mark"] == "line"


def test_session_context_block():
    """Middleware formats state into the session block for the LLM."""
    block = _format_session_block({
        "aoi_refs": [{"name": "Para", "source": "gadm", "src_id": "BRA.14_1", "subtype": "state"}],
        "dataset_id": "tree_cover_loss",
        "data_refs": ["stat_001"],
        "artifact_ids": ["art_001"],
    })
    assert "AOI: Para (gadm:BRA.14_1)" in block
    assert "Dataset: tree_cover_loss" in block
    assert "stat_001" in block
    assert "@art_001" in block

    empty = _format_session_block({})
    assert "AOI: none" in empty
