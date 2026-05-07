from langchain.tools import ToolRuntime, tool


@tool
async def get_artifact(
    artifact_id: str,
    runtime: ToolRuntime = None,
) -> dict:
    """Fetch an artifact by id. Use this to inspect a prior chart's spec
    before modifying it, or to resolve an @-mentioned artifact."""
    store = runtime.store
    item = await store.aget(("artifacts",), artifact_id)
    if item is None:
        return {"error": f"artifact not found: {artifact_id}"}
    return item.value
