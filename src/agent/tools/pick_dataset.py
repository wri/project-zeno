from datetime import datetime
from pathlib import Path
from typing import Annotated, Dict

from langgraph.prebuilt import InjectedState
import pandas as pd
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.types import Command

from src.agent.tools.sub_llm_handlers.dataset_candidate_picker import DatasetCandidatePicker
from src.agent.tools.sub_llm_handlers.dataset_selector import DatasetSelector
from src.agent.tools.data_handlers.analytics_handler import (
    DIST_ALERT_ID,
    GRASSLANDS_ID,
    LAND_COVER_CHANGE_ID,
    TREE_COVER_LOSS_ID,
)
from src.shared.config import SharedSettings
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

data_dir = Path("data")

retriever_cache = None


@tool("pick_dataset")
async def pick_dataset(
    query: str,
    start_date: str,
    end_date: str,
    state: Annotated[Dict, InjectedState] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
) -> Command:
    """
    Given a user query, runs RAG to retrieve relevant datasets, selects the best matching dataset within the specified time range with reasoning,
    and extracts relevant metadata needed for downstream querying.

    Args:
        query: User query providing context for the dataset selection
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
    """
    return await pick_dataset_func(query, start_date, end_date, tool_call_id)


async def pick_dataset_func(
    query: str,
    start_date: str,
    end_date: str,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
    candidate_picker: DatasetCandidatePicker = DatasetCandidatePicker(),
    dataset_selector: DatasetSelector = DatasetSelector(),
) -> Command:
    logger.info("PICK-DATASET-TOOL")
    # Step 1: RAG lookup
    candidate_datasets = await candidate_picker.rag_candidate_datasets(query, k=3)
    # Step 2: LLM to select best dataset and potential context layer
    selection_result = await dataset_selector.select_best_dataset(query, candidate_datasets)

    tool_message = f"""# About the selection
    Selected dataset name: {selection_result.dataset_name}
    Selected context layer: {selection_result.context_layer}
    Reasoning for selection: {selection_result.reason}

    # Additional dataset information

    ## Description

    {selection_result.description}

    ## Function usage notes:

    {selection_result.function_usage_notes}

    ## Usage cautions

    {selection_result.cautions}

    ## Content date

    {selection_result.content_date}
    """

    logger.debug(f"Pick dataset tool message: {tool_message}")

    start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_date = datetime.strptime(end_date, "%Y-%m-%d").date()

    if not selection_result.tile_url.startswith("http"):
        selection_result.tile_url = (
            SharedSettings.eoapi_base_url + selection_result.tile_url
        )

    if selection_result.dataset_id == DIST_ALERT_ID:
        selection_result.tile_url += (
            f"&start_date={start_date}&end_date={end_date}"
        )
    elif selection_result.dataset_id in [LAND_COVER_CHANGE_ID, GRASSLANDS_ID]:
        if end_date.year in range(2000, 2023):
            selection_result.tile_url = selection_result.tile_url.format(
                year=end_date.year
            )
        else:
            selection_result.tile_url = selection_result.tile_url.format(
                year="2022"
            )
    elif selection_result.dataset_id == TREE_COVER_LOSS_ID:
        if end_date.year in range(2001, 2025):
            selection_result.tile_url += (
                f"&start_year={start_date.year}&end_year={end_date.year}"
            )
        else:
            selection_result.tile_url += "&start_year=2001&end_year=2024"

    return Command(
        update={
            "dataset": selection_result.model_dump(),
            "messages": [ToolMessage(tool_message, tool_call_id=tool_call_id)],
        },
    )
