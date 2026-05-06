from typing import Annotated, Sequence

from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages
from typing_extensions import TypedDict

from src.agent.harness.protocol import AoiRef


class AgentState(TypedDict, total=False):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    aoi_refs: list[AoiRef]
    dataset_id: str
    data_refs: list[str]
    artifact_ids: list[str]
