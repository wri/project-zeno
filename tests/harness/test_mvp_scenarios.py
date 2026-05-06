"""Phase 1 dummy MVP validation. These tests exercise the harness
primitives directly — tools, subagents, artifact format, skill loader —
without invoking the orchestrator LLM. The orchestrator is exercised
manually via `python -m src.agent.harness.cli`."""

import asyncio
from pathlib import Path

import pytest

from src.agent.harness.artifact import Artifact
from src.agent.harness.backends.memory import InMemoryBackend
from src.agent.harness.middleware import _format_session_block
from src.agent.harness.protocol import (
    AoiResolvedEvent,
    ArtifactEvent,
    StateDeltaEvent,
    UIContext,
)
from src.agent.harness.session import ZenoSession
from src.agent.harness.skills import all_skills, get_skill_body, load_skills
from src.agent.harness.subagents.analyst import AnalystAgent
from src.agent.harness.subagents.geo import GeoAgent
from src.agent.harness.tools.execute import execute
from src.agent.harness.tools.fetch import fetch
from src.agent.harness.tools.get_artifact import get_artifact
from src.agent.harness.tools.list_datasets import list_datasets
from src.agent.harness.tools.read_skill import read_skill
from src.agent.harness.tools.update_artifact import update_artifact
from src.agent.harness.tools.zoom_map import zoom_map


def _make_session():
    backend = InMemoryBackend()
    session = ZenoSession.__new__(ZenoSession)
    session.backend = backend
    session._events = asyncio.Queue()
    session.state = {
        "aoi_refs": [],
        "dataset_id": None,
        "data_refs": [],
        "artifact_ids": [],
    }
    session.ui_context = UIContext()
    return session


def _drain(session) -> list:
    items = []
    while not session._events.empty():
        items.append(session._events.get_nowait())
    return items


@pytest.mark.asyncio
async def test_scenario_1_targeted_edit():
    session = _make_session()
    seeded = Artifact(
        type="chart",
        title="DIST-ALERT by driver",
        content={
            "spec": {"mark": "line", "encoding": {}},
            "data": [{"driver": "fire", "area_ha": 12.0}],
        },
    )
    await session.backend.save_artifact(seeded)

    result = await update_artifact.ainvoke(
        {
            "artifact_id": seeded.id,
            "changes": {"chart_type": "bar", "title": "Renamed"},
        },
        config={"configurable": {"session": session}},
    )

    assert "error" not in result
    assert result["parent_id"] == seeded.id
    assert result["title"] == "Renamed"
    assert result["content"]["spec"]["mark"] == "bar"

    events = _drain(session)
    art_evts = [e for e in events if isinstance(e, ArtifactEvent)]
    assert len(art_evts) == 1
    assert art_evts[0].artifact.parent_id == seeded.id


@pytest.mark.asyncio
async def test_scenario_2_full_workflow():
    session = _make_session()
    geo = GeoAgent()
    analyst = AnalystAgent(backend=session.backend)

    refs = await geo.resolve("Para")
    assert refs and refs[0]["src_id"] == "BRA.14_1"

    catalog = await list_datasets.ainvoke(
        {"query": "tree cover loss", "limit": 3}
    )
    assert catalog and "id" in catalog[0]
    dataset_id = catalog[0]["id"]

    fetched = await fetch.ainvoke(
        {
            "aoi_refs": refs,
            "dataset_id": dataset_id,
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
        },
        config={"configurable": {"session": session}},
    )
    stat_id = fetched["stat_id"]

    artifact = await analyst.analyze(
        task="analyze deforestation in Para",
        stat_ids=[stat_id],
        dataset_id=dataset_id,
        aoi_refs=refs,
    )
    await session.backend.save_artifact(artifact)
    session.emit(ArtifactEvent(artifact=artifact))

    events = _drain(session)
    types = [type(e).__name__ for e in events]
    assert "DataFetchedEvent" in types
    assert "ArtifactEvent" in types
    assert "StateDeltaEvent" in types

    art = next(e for e in events if isinstance(e, ArtifactEvent)).artifact
    assert art.type == "chart"
    assert art.content["spec"]["mark"] == "bar"
    assert art.content["data"], "chart data should be populated"
    assert art.follow_ups


@pytest.mark.asyncio
async def test_scenario_3_multi_aoi_compare():
    session = _make_session()
    geo = GeoAgent()
    analyst = AnalystAgent(backend=session.backend)

    brazil = await geo.resolve("Brazil")
    peru = await geo.resolve("Peru")
    refs = brazil + peru

    f1 = await fetch.ainvoke(
        {
            "aoi_refs": brazil,
            "dataset_id": "tree_cover_loss",
            "start_date": "2020-01-01",
            "end_date": "2024-12-31",
        },
        config={"configurable": {"session": session}},
    )
    f2 = await fetch.ainvoke(
        {
            "aoi_refs": peru,
            "dataset_id": "tree_cover_loss",
            "start_date": "2020-01-01",
            "end_date": "2024-12-31",
        },
        config={"configurable": {"session": session}},
    )
    assert f1["stat_id"] != f2["stat_id"]

    artifact = await analyst.analyze(
        task="compare Brazil vs Peru for tree cover loss",
        stat_ids=[f1["stat_id"], f2["stat_id"]],
        dataset_id="tree_cover_loss",
        aoi_refs=refs,
    )
    assert artifact.inputs["stat_ids"] == [f1["stat_id"], f2["stat_id"]]
    assert artifact.content["data"]


@pytest.mark.asyncio
async def test_scenario_4_new_tool_drop_in():
    """Adding a new @tool requires only a file + an entry in tools/__init__
    + a mention in factory.py. We assert the harness tools list is wired
    purely from imports — no string-based registry needed."""
    from src.agent.harness import tools as tools_pkg

    expected = {
        "list_datasets",
        "fetch",
        "execute",
        "get_artifact",
        "update_artifact",
        "zoom_map",
        "read_skill",
    }
    assert expected <= set(tools_pkg.__all__)
    for name in expected:
        assert hasattr(tools_pkg, name)


@pytest.mark.asyncio
async def test_scenario_5_new_skill_drop_in():
    """Drop a new SKILL.md into skills_md/ and verify the loader picks it
    up via load_skills() with metadata parsed."""
    skills_dir = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "agent"
        / "harness"
        / "skills_md"
    )
    new_path = skills_dir / "biodiversity.md"
    new_path.write_text(
        "---\n"
        "name: biodiversity\n"
        "description: Biodiversity-focused analysis.\n"
        "when_to_use: User asks about species, KBAs, or habitat loss.\n"
        "---\n\n"
        "# Workflow\n\n1. Resolve KBA via geo_subagent.\n",
    )
    try:
        skills = load_skills()
        names = {s.name for s in skills}
        assert "biodiversity" in names
        body = next(
            s for s in skills if s.name == "biodiversity"
        ).body
        assert "Workflow" in body
    finally:
        new_path.unlink()


@pytest.mark.asyncio
async def test_scenario_6_new_renderer_consumes_events():
    """Multiple renderers should consume the same event sequence. We
    simulate two renderers (text, list-collector) over the same stream."""
    session = _make_session()
    seeded = Artifact(type="chart", title="t", content={"spec": {}, "data": []})
    await session.backend.save_artifact(seeded)
    session.emit(ArtifactEvent(artifact=seeded))
    session.emit(AoiResolvedEvent(aoi_refs=[
        {"name": "Para", "source": "gadm", "src_id": "BRA.14_1", "subtype": "state"}
    ]))

    events = _drain(session)
    text = []
    structured = []
    for ev in events:
        text.append(type(ev).__name__)
        structured.append(ev)
    assert "ArtifactEvent" in text
    assert any(isinstance(e, AoiResolvedEvent) for e in structured)
    assert any(isinstance(e, StateDeltaEvent) for e in structured)


@pytest.mark.asyncio
async def test_scenario_7_at_artifact_edit():
    session = _make_session()
    geo = GeoAgent()
    analyst = AnalystAgent(backend=session.backend)

    refs = await geo.resolve("Para")
    fetched = await fetch.ainvoke(
        {
            "aoi_refs": refs,
            "dataset_id": "tree_cover_loss",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
        },
        config={"configurable": {"session": session}},
    )
    art = await analyst.analyze(
        task="bar chart please",
        stat_ids=[fetched["stat_id"]],
        dataset_id="tree_cover_loss",
        aoi_refs=refs,
    )
    await session.backend.save_artifact(art)
    session.ui_context = UIContext(active_artifact_id=art.id)

    fetched_back = await get_artifact.ainvoke(
        {"artifact_id": art.id},
        config={"configurable": {"session": session}},
    )
    assert fetched_back["id"] == art.id

    pie = await update_artifact.ainvoke(
        {"artifact_id": art.id, "changes": {"chart_type": "pie"}},
        config={"configurable": {"session": session}},
    )
    assert pie["parent_id"] == art.id
    assert pie["content"]["spec"]["mark"] == "pie"


@pytest.mark.asyncio
async def test_scenario_8_session_context_format():
    session = _make_session()
    session.state["aoi_refs"] = [
        {"name": "Para", "source": "gadm", "src_id": "BRA.14_1", "subtype": "state"}
    ]
    session.state["dataset_id"] = "tree_cover_loss"
    session.state["data_refs"] = ["stat_001"]
    session.state["artifact_ids"] = ["art_001"]
    block = _format_session_block(session)
    assert "AOI: Para" in block
    assert "Dataset: tree_cover_loss" in block
    assert "stat_001" in block
    assert "@art_001" in block


@pytest.mark.asyncio
async def test_scenario_9_provider_swap():
    """Swapping the orchestrator model should not require code changes —
    just a different mapping passed to ModelRegistry."""
    from src.agent.harness.models import ModelRegistry

    registry = ModelRegistry({"orchestrator": "sonnet"})
    m = registry.for_langgraph("orchestrator")
    assert m is not None

    registry2 = ModelRegistry({"orchestrator": "haiku"})
    assert registry2.for_langgraph("orchestrator") is not None

    with pytest.raises(ValueError):
        ModelRegistry({"orchestrator": "nope"}).for_langgraph(
            "orchestrator"
        )


@pytest.mark.asyncio
async def test_zoom_map_emits_aoi_event():
    session = _make_session()
    refs = [
        {"name": "Para", "source": "gadm", "src_id": "BRA.14_1", "subtype": "state"}
    ]
    out = await zoom_map.ainvoke(
        {"aoi_refs": refs},
        config={"configurable": {"session": session}},
    )
    assert out == {"zoomed_to": ["Para"]}
    events = _drain(session)
    assert any(isinstance(e, AoiResolvedEvent) for e in events)


@pytest.mark.asyncio
async def test_execute_summary():
    session = _make_session()
    refs = [{"name": "Para", "source": "gadm", "src_id": "BRA.14_1", "subtype": "state"}]
    fetched = await fetch.ainvoke(
        {
            "aoi_refs": refs,
            "dataset_id": "tree_cover_loss",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
        },
        config={"configurable": {"session": session}},
    )
    out = await execute.ainvoke(
        {
            "code": "df['area_ha'].sum()",
            "stat_ids": [fetched["stat_id"]],
        },
        config={"configurable": {"session": session}},
    )
    assert out["row_count"] > 0
    assert out["total_area_ha"] > 0


@pytest.mark.asyncio
async def test_read_skill_returns_body():
    body = await read_skill.ainvoke({"name": "analyze"})
    assert "Workflow" in body
    assert get_skill_body("nonexistent") is None


def test_skills_metadata_loaded():
    skills = all_skills()
    names = {s.name for s in skills}
    assert {"analyze", "compare", "explore"} <= names
