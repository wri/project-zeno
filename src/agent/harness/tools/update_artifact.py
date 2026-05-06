import copy

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from src.agent.harness.artifact import Artifact
from src.agent.harness.protocol import ArtifactEvent

_ALLOWED_KEYS = {"title", "chart_type", "filter", "color", "axis_labels"}


def _apply_changes(artifact: Artifact, changes: dict) -> Artifact:
    new_content = copy.deepcopy(artifact.content)
    new_title = artifact.title

    for key, value in changes.items():
        if key == "title":
            new_title = str(value)
        elif key == "chart_type":
            spec = new_content.setdefault("spec", {})
            spec["mark"] = str(value)
        elif key == "filter":
            data = new_content.get("data") or []
            keep: list[dict] = []
            for row in data:
                if all(row.get(k) == v for k, v in dict(value).items()):
                    keep.append(row)
            new_content["data"] = keep
        elif key == "color":
            spec = new_content.setdefault("spec", {})
            enc = spec.setdefault("encoding", {})
            enc["color"] = {"value": str(value)}
        elif key == "axis_labels":
            spec = new_content.setdefault("spec", {})
            enc = spec.setdefault("encoding", {})
            for axis, label in dict(value).items():
                enc.setdefault(axis, {})["title"] = label

    return Artifact(
        type=artifact.type,
        title=new_title,
        content=new_content,
        query=artifact.query,
        inputs=dict(artifact.inputs),
        code=list(artifact.code),
        follow_ups=list(artifact.follow_ups),
        parent_id=artifact.id,
    )


@tool
async def update_artifact(
    artifact_id: str,
    changes: dict,
    config: RunnableConfig = None,
) -> dict:
    """Apply a presentation-only change to an existing artifact. Allowed
    keys: title, chart_type, filter, color, axis_labels. Produces a new
    artifact with parent_id set to the original. Data, AOI, and date-range
    changes must go through fetch + analyst, not this tool."""
    session = (config or {}).get("configurable", {}).get("session")
    if session is None:
        raise RuntimeError(
            "update_artifact tool requires a session in config"
        )

    invalid = set(changes.keys()) - _ALLOWED_KEYS
    if invalid:
        return {
            "error": (
                f"unsupported change keys: {sorted(invalid)}. "
                f"Allowed: {sorted(_ALLOWED_KEYS)}."
            )
        }

    original = await session.backend.get_artifact(artifact_id)
    if original is None:
        return {"error": f"artifact not found: {artifact_id}"}

    updated = _apply_changes(original, changes)
    await session.backend.save_artifact(updated)
    session.emit(ArtifactEvent(artifact=updated))
    return updated.to_dict()
