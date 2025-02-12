from typing import Annotated, List, Sequence

from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages
from langgraph.managed import IsLastStep
from langgraph.managed.is_last_step import RemainingSteps
from typing_extensions import TypedDict

from zeno.agents.layerfinder.agent import LayerFinderResponse


class LayerFinderState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    question: str
    documents: List[str]
    validated_documents: LayerFinderResponse
    is_last_step: IsLastStep
    remaining_steps: RemainingSteps
    ds_id: str
