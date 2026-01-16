from datetime import datetime
from pathlib import Path
from typing import Annotated, Optional

import pandas as pd
from langchain_core.messages import ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langgraph.types import Command
from pydantic import BaseModel, Field

from src.tools.data_handlers.analytics_handler import (
    DIST_ALERT_ID,
    GRASSLANDS_ID,
    LAND_COVER_CHANGE_ID,
    TREE_COVER_LOSS_BY_DRIVER_ID,
    TREE_COVER_LOSS_ID,
)
from src.tools.datasets_config import DATASETS
from src.utils.config import APISettings
from src.utils.llms import SMALL_MODEL
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

data_dir = Path("data")

retriever_cache = None


async def _get_retriever():
    if retriever_cache is None:
        logger.debug("Loading retriever for the first time...")
        embeddings = GoogleGenerativeAIEmbeddings(
            model=APISettings.dataset_embeddings_model
        )
        index = InMemoryVectorStore.load(
            data_dir / APISettings.dataset_embeddings_db,
            embedding=embeddings,
        )
        _retriever_cache = index.as_retriever(
            search_type="similarity", search_kwargs={"k": 3}
        )
    return _retriever_cache


async def rag_candidate_datasets(query: str, k=3):
    logger.debug(f"Retrieving candidate datasets for query: '{query}'")
    candidate_datasets = []
    retriever = await _get_retriever()
    match_documents = await retriever.ainvoke(query)
    for doc in match_documents:
        data = [ds for ds in DATASETS if ds["dataset_id"] == int(doc.id)]
        if not data:
            raise ValueError(f"No data found for dataset ID: {doc.id}")
        candidate_datasets.append(data[0])

    logger.debug(f"Found {len(candidate_datasets)} candidate datasets.")
    return pd.DataFrame(candidate_datasets)


class DatasetOption(BaseModel):
    dataset_id: int = Field(
        description="ID of the dataset that best matches the user query."
    )
    context_layer: Optional[str] = Field(
        None,
        description="Pick a single context layer from the dataset if useful",
    )
    reason: str = Field(
        description="Short reason why the dataset is the best match."
    )


class DatasetSelectionResult(DatasetOption):
    tile_url: str = Field(
        description="Tile URL of the dataset that best matches the user query.",
    )
    dataset_name: str = Field(
        description="Name of the dataset that best matches the user query."
    )
    analytics_api_endpoint: str = Field(
        description="Analytics API endpoint of the dataset that best matches the user query.",
    )
    description: str = Field(
        description="Description of the dataset that best matches the user query.",
    )
    prompt_instructions: str = Field(
        description="Prompt instructions of the dataset that best matches the user query.",
    )
    methodology: str = Field(
        description="Methodology of the dataset that best matches the user query.",
    )
    cautions: str = Field(
        description="Cautions of the dataset that best matches the user query.",
    )
    function_usage_notes: str = Field(
        description="Function usage notes of the dataset that best matches the user query.",
    )
    citation: str = Field(
        description="Citation of the dataset that best matches the user query.",
    )


async def select_best_dataset(
    query: str, candidate_datasets: pd.DataFrame
) -> DatasetSelectionResult:
    DATASET_SELECTION_PROMPT = ChatPromptTemplate.from_messages(
        [
            (
                "user",
                """Based on the query, return the ID of the dataset that can best answer the
                user query and provide reason why it is the best match.
    Look at the dataset description and contextual layers, as well as date & variables.

    Evaluate if the best dataset is available for the date range requested by the user,
    if not, pick the closest date range but warn the user that there
    is not an exact match with the query requested by the user in the reason field.

    IMPORTANT:
    Provide the selection reason in the same language used in the user query,
    but keep explanations concise. Do not use datset IDs to describe the dataset.
    For instance, instead of saying "Dataset ID: 123", say "Dataset: Tree Cover Loss".

    Candidate datasets:

    {candidate_datasets}

    User query:

    {user_query}
    """,
            )
        ]
    )

    logger.debug("Invoking dataset selection chain...")
    dataset_selection_chain = (
        DATASET_SELECTION_PROMPT
        | SMALL_MODEL.with_structured_output(DatasetOption)
    )
    selection_result = await dataset_selection_chain.ainvoke(
        {
            "candidate_datasets": candidate_datasets[
                [
                    "dataset_id",
                    "dataset_name",
                    "description",
                    "content_date",
                    "cautions",
                    "prompt_instructions",
                    "context_layers",
                ]
            ].to_csv(index=False),
            "user_query": query,
        }
    )
    logger.debug(
        f"Selected dataset ID: {selection_result.dataset_id}. Reason: {selection_result.reason}"
    )

    selected_row = candidate_datasets[
        candidate_datasets.dataset_id == selection_result.dataset_id
    ].iloc[0]

    return DatasetSelectionResult(
        dataset_id=selected_row.dataset_id,
        dataset_name=selected_row.dataset_name,
        context_layer=selection_result.context_layer,
        reason=selection_result.reason,
        tile_url=selected_row.tile_url,
        analytics_api_endpoint=selected_row.analytics_api_endpoint,
        description=selected_row.description,
        prompt_instructions=selected_row.prompt_instructions,
        methodology=selected_row.methodology,
        cautions=selected_row.cautions,
        function_usage_notes=selected_row.function_usage_notes,
        citation=selected_row.citation,
    )


@tool("pick_dataset")
async def pick_dataset(
    query: str,
    start_date: str,
    end_date: str,
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
    logger.info("PICK-DATASET-TOOL")
    # Step 1: RAG lookup
    candidate_datasets = await rag_candidate_datasets(query, k=3)

    # Step 2: LLM to select best dataset and potential context layer
    selection_result = await select_best_dataset(query, candidate_datasets)

    if selection_result.dataset_id == TREE_COVER_LOSS_BY_DRIVER_ID:
        selection_result.context_layer = "driver"

    selected_dataset = [
        ds
        for ds in DATASETS
        if ds["dataset_id"] == selection_result.dataset_id
    ][0]

    tool_message = f"""# About the selection
    Selected dataset name: {selection_result.dataset_name}
    Selected context layer: {selection_result.context_layer}
    Reasoning for selection: {selection_result.reason}

    # Additional dataset information

    ## Description

    {selected_dataset["description"]}

    ## Function usage notes:

    {selected_dataset["function_usage_notes"]}

    ## Usage cautions

    {selected_dataset["cautions"]}

    ## Content date

    {selected_dataset["content_date"]}
    """

    logger.debug(f"Pick dataset tool message: {tool_message}")

    start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_date = datetime.strptime(end_date, "%Y-%m-%d").date()

    if not selection_result.tile_url.startswith("http"):
        selection_result.tile_url = (
            APISettings.eoapi_base_url + selection_result.tile_url
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
