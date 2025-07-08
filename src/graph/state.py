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

    # pick-aoi tool
    aoi: dict
    subregion_aois: dict
    subregion: str
    aoi_name: str
    subtype: str

    # pick-dataset tool
    dataset: dict

    # pull-data tool
    raw_data: dict

    # generate-insights tool
    insights: list
    charts_data: list
    insight_count: int

    # langgraph managed
    is_last_step: IsLastStep
    remaining_steps: RemainingSteps
