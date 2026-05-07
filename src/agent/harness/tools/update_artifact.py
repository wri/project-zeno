import copy
import json

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from src.agent.harness.artifact import Artifact

_ALLOWED_KEYS = {"title", "chart_type", "filter", "color", "axis_labels"}


def _apply_changes(original: dict, changes: dict) -> dict:
    """Apply cosmetic changes to an artifact dict. Returns a new Artifact."""
    new_content = copy.deepcopy(original.get("content", {}))
    new_title = original.get("title", "")

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

    new_artifact = Artifact(
        type=original.get("type", "chart"),
        title=new_title,
        content=new_content,
        query=original.get("query", ""),
        inputs=dict(original.get("inputs", {})),
        code=list(original.get("code", [])),
        follow_ups=list(original.get("follow_ups", [])),
        parent_id=original.get("id"),
    )
    return new_artifact


@tool
async def update_artifact(
    artifact_id: str,
    changes: dict,
    runtime: ToolRuntime = None,
) -> Command:
    """Apply a presentation-only change to an existing artifact. Allowed
    keys: title, chart_type, filter, color, axis_labels. Produces a new
    artifact with parent_id set to the original. Data, AOI, and date-range
    changes must go through fetch + analyst, not this tool."""
    invalid = set(changes.keys()) - _ALLOWED_KEYS
    if invalid:
        return Command(update={
            "messages": [ToolMessage(
                content=json.dumps({
                    "error": (
                        f"unsupported change keys: {sorted(invalid)}. "
                        f"Allowed: {sorted(_ALLOWED_KEYS)}."
                    )
                }),
                tool_call_id=runtime.tool_call_id,
            )],
        })

    store = runtime.store
    item = await store.aget(("artifacts",), artifact_id)
    if item is None:
        return Command(update={
            "messages": [ToolMessage(
                content=json.dumps({"error": f"artifact not found: {artifact_id}"}),
                tool_call_id=runtime.tool_call_id,
            )],
        })

    updated = _apply_changes(item.value, changes)
    await store.aput(("artifacts",), updated.id, updated.to_dict())
    runtime.stream_writer({"type": "artifact", "artifact": updated.to_dict()})
    return Command(update={
        "artifact_ids": [updated.id],
        "messages": [ToolMessage(
            content=json.dumps(updated.to_dict()),
            tool_call_id=runtime.tool_call_id,
        )],
    })
