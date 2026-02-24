import operator
from typing import Annotated, Sequence

from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages
from typing_extensions import TypedDict

from src.agent.tools.code_executors.base import CodeActPart


class AOISelection(TypedDict):
    name: str
    aois: list[dict]


class Statistics(TypedDict):
    dataset_name: str
    start_date: str
    end_date: str
    source_url: str
    data: dict
    aoi_names: list[str]


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    user_persona: str

    # pick-aoi tool
    aoi: dict
    subtype: str
    aoi_selection: AOISelection

    # pick-dataset tool
    dataset: dict

    # pull-data tool
    start_date: str
    end_date: str
    statistics: Annotated[list[Statistics], operator.add]

    # generate-insights tool
    insights: list
    charts_data: list
    codeact_parts: list[CodeActPart]
