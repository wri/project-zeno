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
    dataset_id: NotRequired[int | None]
    start_date: str
    end_date: str
    source_url: NotRequired[str]
    # Empty for ID-backed statistics; use fetch_statistics_from_url(source_url).
    data: NotRequired[dict]
    # Mapping from aoi_id value to human-readable name, built at pull time and
    # re-applied after URL fetch so chart labels stay readable.
    aoi_id_to_name: NotRequired[dict]
    aoi_names: list[str]
    # src_ids of the analysed AOIs, parallel to aoi_names; aoi_sources carries
    # the matching source per id since src_id is only unique per source.
    aoi_ids: NotRequired[list[str]]
    aoi_sources: NotRequired[list[str]]
    parameters: list[StatisticsParameter] | None
    context_layer: str | None


class EncodedCodeActPart(TypedDict):
    type: str
    content: str


class Nudge(TypedDict):
    # Free-form category, not an enum — same convention as the plain-string
    # msg_type tags on ToolMessage.response_metadata. Known values so far:
    # "dataset_choice" (pick_dataset alternatives), "aoi_choice" (pick_aoi
    # same-name-different-country disambiguation), "dashboard_choice" /
    # "insight_choice" (create-new vs update-current, see the dashboard
    # skill and update_insight_display), plus whatever send_nudge is called
    # with directly (e.g. "confirm", "clarify").
    type: str
    # Clickable choices; clicking one resubmits it as the next human
    # message — no dedicated resolver tool, same mechanism
    # follow_up_suggestions already relies on.
    options: list[str]


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    user_persona: str

    # Ambient frontend view state (what the user is currently looking at):
    # page, map viewport, visible layers/AOIs. Last-write-wins each turn —
    # no reducer; we only ever want the latest snapshot. Read on demand via
    # the inspect_view_context tool, not eagerly injected into the prompt.
    view_context: dict

    # pick-aoi tool
    aoi_selection: AOISelection

    # pick-dataset tool
    dataset: dict

    # send_nudge tool — generic "offer the user clickable options" signal,
    # also used by pick-dataset to offer dataset alternatives. Last-write-
    # wins, no reducer.
    nudge: Nudge

    # pull-data tool
    start_date: str
    end_date: str
    statistics: Annotated[list[Statistics], operator.add]

    # show-imagery tool (see ImageryState in src.agent.models for structure)
    imagery: dict

    # search-blogs tool
    cited_articles: Annotated[list[CitedArticle], operator.add]

    # create-dashboard / add-to-dashboard tools — the dashboard the
    # conversation is working on (last created or added-to this thread).
    dashboard_id: str

    # generate-insights tool
    insight: str
    follow_up_suggestions: list[str]
    insight_id: str
    charts_data: list
    codeact_parts: list[EncodedCodeActPart]
