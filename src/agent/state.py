import operator
from typing import Annotated, Any, Sequence

from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages
from typing_extensions import TypedDict


class AOISelection(TypedDict):
    name: str
    aois: list[dict]


class StatisticsParameter(TypedDict):
    name: str
    values: list[Any]


class Statistics(TypedDict):
    dataset_name: str
    start_date: str
    end_date: str
    source_url: str
    data: dict
    aoi_names: list[str]
    parameters: list[StatisticsParameter] | None
    context_layer: str | None


class EncodedCodeActPart(TypedDict):
    type: str
    content: str


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
    insight: str
    follow_up_suggestions: list[str]
    charts_data: list
    codeact_parts: list[EncodedCodeActPart]
