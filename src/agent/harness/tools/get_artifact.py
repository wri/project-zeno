from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool


@tool
async def get_artifact(
    artifact_id: str,
    config: RunnableConfig = None,
) -> dict:
    """Fetch an artifact by id. Use this to inspect a prior chart's spec
    before modifying it, or to resolve an @-mentioned artifact."""
    session = (config or {}).get("configurable", {}).get("session")
    if session is None:
        raise RuntimeError("get_artifact tool requires a session in config")
    artifact = await session.backend.get_artifact(artifact_id)
    if artifact is None:
        return {"error": f"artifact not found: {artifact_id}"}
    return artifact.to_dict()
