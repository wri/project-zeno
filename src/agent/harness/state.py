from typing import Annotated

from langchain.agents import AgentState
from typing_extensions import TypedDict

AoiRef = TypedDict(
    "AoiRef",
    {"name": str, "source": str, "src_id": str, "subtype": str | None},
    total=False,
)


def _append_refs(existing: list[str], new: list[str]) -> list[str]:
    """Reducer that appends new refs to existing list (deduplicating)."""
    seen = set(existing)
    return existing + [r for r in new if r not in seen]


def _replace_aoi(existing: list[AoiRef], new: list[AoiRef]) -> list[AoiRef]:
    """Reducer that replaces AOI refs entirely on each update."""
    return new


def _append_artifact_ids(existing: list[str], new: list[str]) -> list[str]:
    """Reducer that appends artifact IDs."""
    seen = set(existing)
    return existing + [a for a in new if a not in seen]


class ZenoState(AgentState, total=False):
    """Extends AgentState with Zeno-specific fields.

    Inherits: messages (with add_messages reducer), jump_to, structured_response.
    Adds: aoi_refs, dataset_id, data_refs, artifact_ids.
    """

    aoi_refs: Annotated[list[AoiRef], _replace_aoi]
    dataset_id: str
    data_refs: Annotated[list[str], _append_refs]
    artifact_ids: Annotated[list[str], _append_artifact_ids]
