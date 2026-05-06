from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from src.agent.harness.protocol import AoiResolvedEvent, ArtifactEvent
from src.agent.harness.subagents.analyst import AnalystAgent
from src.agent.harness.subagents.geo import GeoAgent


def make_geo_tool(geo: GeoAgent):
    @tool
    async def geo_subagent(
        query: str,
        config: RunnableConfig = None,
    ) -> list[dict]:
        """Resolve a place-name query (e.g. "Para, Brazil", "neighbours of
        Odisha", "1km buffer around Yellowstone") to one or more AOI refs.
        Returns [{name, source, src_id, subtype}]. Side-effect: emits an
        AoiResolvedEvent so the map knows to highlight the area."""
        session = (config or {}).get("configurable", {}).get("session")
        refs = await geo.resolve(query)
        if session is not None:
            session.emit(AoiResolvedEvent(aoi_refs=list(refs)))
        return [dict(r) for r in refs]

    return geo_subagent


def make_analyst_tool(analyst: AnalystAgent):
    @tool
    async def analyst_subagent(
        task: str,
        stat_ids: list[str],
        dataset_id: str = "",
        aoi_refs: list[dict] | None = None,
        config: RunnableConfig = None,
    ) -> dict:
        """Build a chart artifact answering `task` from cached data
        referenced by stat_ids. Returns {artifact_id, title, type,
        follow_ups}. The full artifact is delivered to the frontend via an
        ArtifactEvent on the same stream."""
        session = (config or {}).get("configurable", {}).get("session")
        artifact = await analyst.analyze(
            task=task,
            stat_ids=stat_ids,
            dataset_id=dataset_id or None,
            aoi_refs=aoi_refs,
        )
        if session is not None:
            await session.backend.save_artifact(artifact)
            session.emit(ArtifactEvent(artifact=artifact))
        return {
            "artifact_id": artifact.id,
            "title": artifact.title,
            "type": artifact.type,
            "follow_ups": artifact.follow_ups,
        }

    return analyst_subagent
