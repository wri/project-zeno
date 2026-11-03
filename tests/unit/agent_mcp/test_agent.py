"""The MCP agent, driven by a scripted model through the in-process MCP
server: the stream updates carry what the frontend reads.

project-zeno-next dispatches on the tool message's name and reads the state
keys of the same "tools" update (parse-stream-message.ts, chatStore.ts and
the handlers in app/store/chat-tools/), so these tests pin those shapes.
"""

import json

import pytest
from fastmcp.server.middleware.rate_limiting import (
    SlidingWindowRateLimitingMiddleware,
)
from langchain_core.language_models.fake_chat_models import (
    GenericFakeChatModel,
)
from langchain_core.load import dumps
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

import src.agent_mcp.graph as mcp_graph
import src.mcp.data as data
from src.agent.datasets.handlers.base import DataPullResult
from src.agent.subagents.pick_dataset.schema import DatasetSelectionResult
from src.agent_mcp.graph import fetch_mcp_agent, mcp_session_block
from src.agent_mcp.tools import mcp_tools
from src.mcp.areas import parse_aoi_id
from src.mcp.server import mcp_server
from tests.unit.agent.tools.pick_aoi.conftest import _patch_search, _row

PARA_ROW = _row(
    "BRA.14_1", "Pará, Brazil", subtype="state-province", score=0.9
)
CORDOBA_ARG = _row(
    "ARG.6_1", "Córdoba, Argentina", subtype="state-province", leaf="Córdoba"
)
CORDOBA_ESP = _row(
    "ESP.2_1", "Córdoba, Spain", subtype="state-province", leaf="Córdoba"
)
PARA = {
    "source": "gadm",
    "src_id": "BRA.14_1",
    "name": "Pará, Brazil",
    "subtype": "state-province",
    "bbox": [-58.9, -9.8, -46.0, 2.6],
}
LOSS = {
    "aoi_id": ["BRA.14", "BRA.14"],
    "aoi_type": ["admin", "admin"],
    "tree_cover_loss_year": [2020, 2021],
    "area_ha": [805620.12, 693512.76],
}


class ScriptedModel(GenericFakeChatModel):
    """Answers with the scripted messages in order, whatever the tools."""

    def bind_tools(self, tools, **kwargs):
        return self


def _call(name: str, args: dict, n: int) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"id": f"call-{n}", "name": name, "args": args}],
    )


@pytest.fixture(autouse=True)
def fresh_rate_limit():
    for middleware in mcp_server.middleware:
        if isinstance(middleware, SlidingWindowRateLimitingMiddleware):
            middleware.limiters.clear()


@pytest.fixture(autouse=True)
def stubbed_data(monkeypatch):
    async def fake_lookup(aoi_ids):
        # The id checks run as in the real lookup; only the database is out.
        for aoi_id in aoi_ids:
            parse_aoi_id(aoi_id)
        return [dict(PARA)]

    async def fake_pull(self, **kwargs):
        return DataPullResult(
            success=True,
            data=dict(LOSS),
            message="ok",
            data_points_count=2,
            analytics_api_url="http://analytics.test/v0/result/ab485026",
        )

    monkeypatch.setattr(data, "lookup_areas", fake_lookup)
    monkeypatch.setattr(data.AnalyticsHandler, "pull_data", fake_pull)


async def _run(monkeypatch, script: list[AIMessage], state: dict = None):
    monkeypatch.setattr(
        mcp_graph, "MODEL", ScriptedModel(messages=iter(script))
    )
    monkeypatch.setattr(mcp_graph, "FALLBACK_MODELS", [])
    agent = await fetch_mcp_agent(checkpointer=InMemorySaver())
    updates = []
    async for update in agent.astream(
        {"messages": [HumanMessage("question")], **(state or {})},
        config={"configurable": {"thread_id": "t"}},
        stream_mode="updates",
    ):
        node = next(iter(update))
        # The API streams each update through langchain's dumps.
        dumps(update[node])
        updates.append((node, update[node]))
    return updates


def _tool_updates(updates) -> dict[str, dict]:
    found = {}
    for node, update in updates:
        if node == "tools":
            found[update["messages"][-1].name] = update
    return found


async def test_the_tools_keep_the_names_the_frontend_dispatches_on():
    names = {tool.name for tool in await mcp_tools()}

    assert {
        "pick_aoi",
        "pick_dataset",
        "pull_data",
        "generate_insights",
    } <= names
    assert not names & {"resolve_areas", "get_dataset", "curated_charts"}


async def test_an_analysis_streams_the_state_the_frontend_reads(monkeypatch):
    _patch_search(monkeypatch, {"Para, Brazil": [PARA_ROW]})
    pull = {"aoi_ids": ["gadm:BRA.14_1"], "dataset_id": 4}
    script = [
        _call("pick_aoi", {"places": [{"place": "Para, Brazil"}]}, 1),
        _call(
            "pick_dataset",
            {"dataset_id": 4, "canopy_cover": 30, "reason": "Loss."},
            2,
        ),
        _call("generate_insights", pull, 3),
        AIMessage(content="Pará lost 693,513 ha in 2021."),
    ]

    tools = _tool_updates(await _run(monkeypatch, script))

    # pickAoi.ts: aoi_selection.aois with source/src_id for the geometry
    # fetch and bbox for the fly-to.
    selection = tools["pick_aoi"]["aoi_selection"]
    assert selection["aois"] == [
        {**PARA, "bbox": selection["aois"][0]["bbox"]}
    ]
    assert len(selection["aois"][0]["bbox"]) == 4

    # pickDataset.ts: a dataset with tile_url or layers makes the card.
    dataset = tools["pick_dataset"]["dataset"]
    assert dataset["dataset_id"] == 4
    assert "tree_cover_density_threshold=30" in dataset["tile_url"]
    assert dataset["layers"]
    assert set(dataset) == set(DatasetSelectionResult.model_fields)

    # generateInsights.ts: camelCase charts, curated (no codeact parts).
    insights = tools["generate_insights"]
    assert insights["codeact_parts"] == []
    chart = insights["charts_data"][0]
    assert {"id", "title", "type", "data", "xAxis", "yAxis"} <= set(chart)
    assert chart["data"]

    # The artifact (rows, provenance, script) is neither streamed nor kept.
    for update in tools.values():
        assert update["messages"][-1].artifact is None


async def test_a_name_in_two_countries_offers_a_choice(monkeypatch):
    _patch_search(monkeypatch, {"Cordoba": [CORDOBA_ARG, CORDOBA_ESP]})
    script = [
        _call("pick_aoi", {"places": [{"place": "Cordoba"}]}, 1),
        AIMessage(content="Which Córdoba do you mean?"),
    ]

    update = _tool_updates(await _run(monkeypatch, script))["pick_aoi"]

    assert "aoi_selection" not in update
    nudge = update["nudge"]
    assert nudge["type"] == "aoi_choice"
    assert len(nudge["options"]) == len(nudge["data"]) == 2
    assert {aoi["src_id"] for aoi in nudge["data"]} == {"ARG.6_1", "ESP.2_1"}


async def test_a_refusal_is_an_error_message_and_writes_no_state(
    monkeypatch,
):
    script = [
        _call(
            "generate_insights",
            {"aoi_ids": ["custom:abc"], "dataset_id": 4},
            1,
        ),
        AIMessage(content="Custom areas are not available."),
    ]

    update = _tool_updates(await _run(monkeypatch, script))[
        "generate_insights"
    ]

    message = update["messages"][-1]
    assert message.status == "error"
    assert "Custom areas are not available" in message.content
    assert set(update) == {"messages"}


def test_the_session_block_gives_the_ids_of_a_map_selection():
    # What stream_chat writes for a ui_context aoi_selected/dataset_selected.
    state = {
        "aoi_selection": {"name": "Pará", "aois": [PARA]},
        "dataset": {
            "dataset_id": 4,
            "dataset_name": "Tree cover loss",
            "context_layer": "driver",
            "parameters": [{"name": "canopy_cover", "values": [30]}],
        },
        "start_date": "2015-01-01",
        "end_date": "2024-12-31",
    }

    line = mcp_session_block(state).splitlines()[-1]

    assert line == (
        "Tool ids: aoi_ids=gadm:BRA.14_1; dataset_id=4; "
        "context_layer=driver; canopy_cover=30; "
        "start_date=2015-01-01, end_date=2024-12-31"
    )
    assert mcp_session_block({}).endswith("Tool ids: none")


async def test_the_tool_texts_use_the_agent_names():
    tools = {tool.name: tool for tool in await mcp_tools()}

    text = json.dumps({n: t.description for n, t in tools.items()})
    assert "resolve_areas" not in text
    assert "curated_charts" not in text
