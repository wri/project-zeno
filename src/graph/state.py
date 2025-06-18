from typing import Annotated, Sequence
import pandas as pd

from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages
from langgraph.managed import IsLastStep
from langgraph.managed.is_last_step import RemainingSteps
from typing_extensions import TypedDict


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    user_persona: str
    aoi: dict
    subregion_aois: pd.DataFrame
    subregion: str
    aoi_name: str
    subtype: str
    dataset: dict
    raw_data: dict
    insights: list
    is_last_step: IsLastStep
    remaining_steps: RemainingSteps