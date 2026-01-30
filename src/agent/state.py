from typing import Annotated, Sequence

from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages
from typing_extensions import TypedDict

from src.agent.tools.code_executors.base import CodeActPart


class AOISelection(TypedDict):
    name: str
    aois: list[dict]


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    user_persona: str

    # pick-aoi tool
    aoi_selection: AOISelection

    # pick-dataset tool
    dataset: dict

    # pull-data tool
    raw_data: dict
    start_date: str
    end_date: str

    # generate-insights tool
    insights: list
    charts_data: list
    codeact_parts: list[CodeActPart]
