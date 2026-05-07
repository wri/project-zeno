from langchain.tools import ToolRuntime, tool


@tool
async def zoom_map(
    aoi_refs: list[dict],
    runtime: ToolRuntime = None,
) -> dict:
    """Tell the frontend to pan and zoom to the given AOI refs. Side-effect
    only: streams a zoom event and returns a confirmation."""
    refs = [dict(r) for r in aoi_refs]
    runtime.stream_writer({"type": "zoom_map", "aoi_refs": refs})
    return {"zoomed_to": [r.get("name") for r in refs]}
