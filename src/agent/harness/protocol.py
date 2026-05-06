from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict, Union

from src.agent.harness.artifact import Artifact


@dataclass
class MessagePreview:
    role: str
    text: str
    tool_calls: list[str] = field(default_factory=list)


class AoiRef(TypedDict):
    name: str
    source: str
    src_id: str
    subtype: str | None


class ChartContent(TypedDict):
    spec: dict
    data: list[dict]


class MapContent(TypedDict):
    layers: list[dict]
    viewport: dict


class InsightContent(TypedDict):
    text: str
    summary: str


class TableContent(TypedDict):
    columns: list[str]
    rows: list[list[Any]]


@dataclass
class StateDeltaEvent:
    update: dict
    type: Literal["state_delta"] = "state_delta"


@dataclass
class AoiResolvedEvent:
    aoi_refs: list[AoiRef]
    type: Literal["aoi_resolved"] = "aoi_resolved"


@dataclass
class DataFetchedEvent:
    stat_id: str
    meta: dict
    type: Literal["data_fetched"] = "data_fetched"


@dataclass
class ArtifactEvent:
    artifact: Artifact
    type: Literal["artifact"] = "artifact"


@dataclass
class MessageEvent:
    role: str
    content: str
    type: Literal["message"] = "message"


@dataclass
class ThinkingEvent:
    text: str
    type: Literal["thinking"] = "thinking"


@dataclass
class ErrorEvent:
    message: str
    recoverable: bool = True
    type: Literal["error"] = "error"


@dataclass
class ContextEvent:
    """Snapshot of what the orchestrator sees at the start of a model
    call: the rendered session block that gets prepended, plus a tail of
    the message history."""

    system_block: str
    message_count: int
    recent: list[MessagePreview]
    type: Literal["context"] = "context"


@dataclass
class ToolCallEvent:
    name: str
    args: dict
    call_id: str = ""
    type: Literal["tool_call"] = "tool_call"


@dataclass
class ToolResultEvent:
    name: str
    call_id: str
    result: Any
    type: Literal["tool_result"] = "tool_result"


ZenoEvent = Union[
    StateDeltaEvent,
    AoiResolvedEvent,
    DataFetchedEvent,
    ArtifactEvent,
    MessageEvent,
    ThinkingEvent,
    ErrorEvent,
    ContextEvent,
    ToolCallEvent,
    ToolResultEvent,
]


@dataclass
class UIContext:
    active_artifact_id: str | None = None
    viewport: dict | None = None
    selected_aoi: str | None = None
    date_range: dict | None = None
    extras: dict = field(default_factory=dict)
