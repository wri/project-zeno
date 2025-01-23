from typing import Annotated, Sequence

from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages
from langgraph.managed import IsLastStep
from langgraph.managed.is_last_step import RemainingSteps
from typing_extensions import TypedDict

from zeno.agents.kba.agent import KBAResponse


class KbaState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    user_persona: str
    report: KBAResponse
    is_last_step: IsLastStep
    remaining_steps: RemainingSteps
