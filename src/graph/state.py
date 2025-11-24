from typing import Annotated, Sequence

from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages
from langgraph.managed import IsLastStep
from langgraph.managed.is_last_step import RemainingSteps
from typing_extensions import TypedDict


def add_aois(left, right):
    """Merges two AOIs and returns the merged AOI."""
    # Convert to lists if needed, but handle empty cases
    if not isinstance(left, list):
        left = [left]
    if not isinstance(right, list):
        right = [right]
    return left + right


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    user_persona: str

    # pick-aoi tool
    aoi: dict
    subregion_aois: dict
    subregion: str
    aoi_name: str
    subtype: str
    aoi_options: Annotated[list[dict], add_aois]

    # pick-dataset tool
    dataset: dict

    # pull-data tool
    raw_data: dict
    start_date: str
    end_date: str

    # generate-insights tool
    insights: list
    charts_data: list
    text_output: str
    code_blocks: list[str]
    execution_outputs: list[str]
    source_urls: list[str]

    # langgraph managed
    is_last_step: IsLastStep
    remaining_steps: RemainingSteps
