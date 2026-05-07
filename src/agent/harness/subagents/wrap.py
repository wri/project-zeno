"""Tool wrappers for subagents. Each returns a Command to update state."""

import json

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from src.agent.harness.subagents.analyst import AnalystAgent
from src.agent.harness.subagents.geo import GeoAgent


def make_geo_tool(geo: GeoAgent):
    @tool
    async def geo_subagent(query: str, runtime: ToolRuntime) -> Command:
        """Resolve a place-name query (e.g. "Para, Brazil", "neighbours of
        Odisha", "1km buffer around Yellowstone") to one or more AOI refs.
        Returns [{name, source, src_id, subtype}]. Updates state.aoi_refs."""
        refs = await geo.resolve(query)
        ref_dicts = [dict(r) for r in refs]
        runtime.stream_writer({"type": "aoi_resolved", "aoi_refs": ref_dicts})
        return Command(update={
            "aoi_refs": refs,
            "messages": [ToolMessage(
                content=json.dumps(ref_dicts),
                tool_call_id=runtime.tool_call_id,
            )],
        })

    return geo_subagent


def make_analyst_tool(analyst: AnalystAgent):
    @tool
    async def analyst_subagent(
        task: str,
        stat_ids: list[str],
        dataset_id: str = "",
        aoi_refs: list[dict] | None = None,
        runtime: ToolRuntime = None,
    ) -> Command:
        """Build a chart artifact answering `task` from cached data
        referenced by stat_ids. Returns artifact summary and updates
        state.artifact_ids."""
        artifact = await analyst.analyze(
            task=task,
            stat_ids=stat_ids,
            dataset_id=dataset_id or None,
            aoi_refs=aoi_refs,
        )
        store = runtime.store
        if store is not None:
            await store.aput(("artifacts",), artifact.id, artifact.to_dict())
        runtime.stream_writer({
            "type": "artifact",
            "artifact": artifact.to_dict(),
        })
        summary = {
            "artifact_id": artifact.id,
            "title": artifact.title,
            "type": artifact.type,
            "follow_ups": artifact.follow_ups,
        }
        return Command(update={
            "artifact_ids": [artifact.id],
            "messages": [ToolMessage(
                content=json.dumps(summary),
                tool_call_id=runtime.tool_call_id,
            )],
        })

    return analyst_subagent
