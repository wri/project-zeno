import operator
from typing import Annotated, Any, Sequence

from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages
from typing_extensions import NotRequired, TypedDict


class CitedArticle(TypedDict):
    id: str
    source: str
    slug: str
    title: str
    abstract: str
    url: str
    lastmod: str
    image: str
    image_alt: str


class AOISelection(TypedDict):
    name: str
    aois: list[dict]


class StatisticsParameter(TypedDict):
    name: str
    values: list[Any]


class Statistics(TypedDict):
    id: NotRequired[str]
    dataset_name: str
    start_date: str
    end_date: str
    source_url: NotRequired[str]
    # Empty for ID-backed statistics; use fetch_statistics_from_url(source_url).
    data: NotRequired[dict]
    # Mapping from aoi_id value to human-readable name, built at pull time and
    # re-applied after URL fetch so chart labels stay readable.
    aoi_id_to_name: NotRequired[dict]
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
    aoi_selection: AOISelection

    # pick-dataset tool
    dataset: dict
    suggested_datasets: list[dict]

    # pull-data tool
    start_date: str
    end_date: str
    statistics: Annotated[list[Statistics], operator.add]

    # show-imagery tool (see ImageryState in src.agent.models for structure)
    imagery: dict

    # search-blogs tool
    cited_articles: Annotated[list[CitedArticle], operator.add]

    # generate-insights tool
    insight: str
    follow_up_suggestions: list[str]
    insight_id: str
    charts_data: list
    codeact_parts: list[EncodedCodeActPart]
