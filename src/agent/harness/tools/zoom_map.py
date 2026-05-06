from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from src.agent.harness.protocol import AoiResolvedEvent


@tool
async def zoom_map(
    aoi_refs: list[dict],
    config: RunnableConfig = None,
) -> dict:
    """Tell the frontend to pan and zoom to the given AOI refs. Side-effect
    only: emits an AoiResolvedEvent and returns a confirmation."""
    session = (config or {}).get("configurable", {}).get("session")
    if session is None:
        raise RuntimeError("zoom_map tool requires a session in config")
    refs = [dict(r) for r in aoi_refs]
    session.emit(AoiResolvedEvent(aoi_refs=refs))
    return {"zoomed_to": [r.get("name") for r in refs]}
