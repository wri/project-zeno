from typing import Annotated, List, Sequence

from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages
from langgraph.managed import IsLastStep
from langgraph.managed.is_last_step import RemainingSteps
from typing_extensions import TypedDict

from zeno.agents.layerfinder.agent import Dataset


class LayerFinderState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    question: str
    datasets: List[Dataset]
    is_last_step: IsLastStep
    remaining_steps: RemainingSteps
