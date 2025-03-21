from typing import Annotated, Sequence, Optional

from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages
from langgraph.managed import IsLastStep
from langgraph.managed.is_last_step import RemainingSteps
from typing_extensions import TypedDict


class GFWDataAPIState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    is_last_step: IsLastStep
    remaining_steps: RemainingSteps
    user_query: Optional[str] = ""
    sql_query: Optional[str] = ""
    error: Optional[str] = ""
