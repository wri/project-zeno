from datetime import datetime
from pathlib import Path
from typing import Annotated, Dict, Optional, Union

import pandas as pd
from langchain.tools import InjectedState
from langchain_core.messages import ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langgraph.types import Command
from pydantic import BaseModel, Field, field_validator, model_validator
from shapely import box

from src.agent.llms import SMALL_MODEL
from src.agent.tools.data_handlers.analytics_handler import (
    DIST_ALERT_ID,
    GRASSLANDS_ID,
    LAND_COVER_CHANGE_ID,
    TREE_COVER_LOSS_BY_DRIVER_ID,
    TREE_COVER_LOSS_ID,
)
from src.agent.tools.datasets_config import DATASETS
from src.shared.config import SharedSettings
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

data_dir = Path("data")

retriever_cache = None


async def _get_retriever():
    global retriever_cache
    if retriever_cache is None:
        logger.debug("Loading retriever for the first time...")
        embeddings = GoogleGenerativeAIEmbeddings(
            model=SharedSettings.dataset_embeddings_model,
            task_type=SharedSettings.dataset_embeddings_task_type,
        )
        index = InMemoryVectorStore.load(
            data_dir / SharedSettings.dataset_embeddings_db,
            embedding=embeddings,
        )
        retriever_cache = index.as_retriever(
            search_type="similarity", search_kwargs={"k": 3}
        )
    return retriever_cache


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
        description="Pick a single context layer from the dataset if relevant.",
    )
    reason: str = Field(
        description="Short reason why the dataset is the best match."
    )
    language: str = Field(
        description="Language of the user query.",
    )

    @field_validator("dataset_id")
    def validate_dataset_id(cls, v):
        if v not in [ds["dataset_id"] for ds in DATASETS]:
            raise ValueError(f"Invalid dataset ID: {v}")
        return v

    @model_validator(mode="after")
    def validate_context_layer_for_dataset(self) -> "DatasetOption":
        """Ensure context_layer is valid for the chosen dataset_id (runs after all fields)."""
        dataset_id = self.dataset_id
        if dataset_id is None:
            self.context_layer = None
            return self
        # Hardcoded override: TCL by driver always needs "driver" intersection
        elif dataset_id == TREE_COVER_LOSS_BY_DRIVER_ID:
            self.context_layer = "driver"
            return self

        if self.context_layer is None:
            return self

        selected_dataset = [
            ds for ds in DATASETS if ds["dataset_id"] == dataset_id
        ][0]
        context_layers = selected_dataset.get("context_layers") or []
        context_layer_values = [lyr["value"] for lyr in context_layers]
        if self.context_layer not in context_layer_values:
            self.context_layer = None

        return self


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
    content_date: str = Field(
        description="Content date of the dataset that best matches the user query.",
    )
    # Tiered instruction fields (PoC) — None for datasets that haven't been migrated
    selection_hints: Optional[str] = Field(
        default=None,
        description="When to prefer this dataset over alternatives.",
    )
    code_instructions: Optional[str] = Field(
        default=None,
        description="Chart type restrictions and data shaping rules for the code executor.",
    )
    presentation_instructions: Optional[str] = Field(
        default=None,
        description="Terminology, tone, and how to describe results to users.",
    )


async def select_best_dataset(
    query: str, candidate_datasets: pd.DataFrame, aoi_selection=None
) -> DatasetSelectionResult:
    DATASET_SELECTION_PROMPT = ChatPromptTemplate.from_messages(
        [
            (
                "user",
                """Based on the query, return the ID of the dataset that can best answer the
    user query and provide reason why it is the best match. Always return at least one dataset.
    Use all information provided to decide which dataset is the best match, especially the selection hints.

    Select a single context layer from the filtered_context_layers in candidate datasets for the dataset if relevant for the user query.
    Context layers allow differentiating between different types of data within the same dataset. So if a user asks
    to show something like "show me tree cover loss by driver", you should select a context layer. These are pre-filtered
    to match the spatiotemporal query constraints.

    Evaluate if the best dataset is available for the date range requested by the user,
    if not, pick the closest date range but warn the user that there
    is not an exact match with the query requested by the user in the reason field.

    Pick the most granular dataset/contextual layer that matches the query, requested time range.
    For instance, dont select tree cover loss by driver if the user requests a specific time range,
    pick tree cover loss instead.

    Keep explanations concise. Do not use datset IDs to describe the dataset.
    For instance, instead of saying "Dataset ID: 123", say "Dataset: Tree Cover Loss".

    Use the language of the user query to generate the reason.

    Candidate datasets:

    {candidate_datasets}

    User query:

    {user_query}

    The following contextual layers can not be picked right now for the listed reasons:

    {removed_layers}

    """,
            )
        ]
    )

    logger.debug("Invoking dataset selection chain...")
    dataset_selection_chain = (
        DATASET_SELECTION_PROMPT
        | SMALL_MODEL.with_structured_output(DatasetOption)
    )

    if aoi_selection is None:
        candidate_datasets["filtered_context_layers"] = candidate_datasets[
            "context_layers"
        ]
        removed_df = None
    else:
        filtered_layers, removed_layers = get_filtered_contextual_layers(
            candidate_datasets["context_layers"], aoi_selection
        )

        candidate_datasets["filtered_context_layers"] = filtered_layers
        removed_df = removed_layers.to_csv(index=False)

    selection_result = await dataset_selection_chain.ainvoke(
        {
            "candidate_datasets": candidate_datasets[
                [
                    "dataset_id",
                    "dataset_name",
                    "description",
                    "selection_hints",
                    "content_date",
                    "filtered_context_layers",
                ]
            ].to_csv(index=False),
            "user_query": query,
            "removed_layers": removed_df,
        }
    )
    logger.debug(
        f"Selected dataset ID: {selection_result.dataset_id}. "
        f"context_layer={selection_result.context_layer!r} (type={type(selection_result.context_layer).__name__}). "
        f"Reason: {selection_result.reason}"
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
        content_date=selected_row.content_date,
        language=selection_result.language,
        selection_hints=selected_row.selection_hints,
        code_instructions=selected_row.code_instructions,
        presentation_instructions=selected_row.presentation_instructions,
    )


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
    logger.info("PICK-DATASET-TOOL")

    aoi_selection = state.get("aoi_selection")

    # Step 1: RAG lookup
    candidate_datasets = await rag_candidate_datasets(query, k=3)
    # Step 2: LLM to select best dataset and potential context layer
    selection_result = await select_best_dataset(
        query, candidate_datasets, aoi_selection
    )

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


def get_filtered_contextual_layers(
    context_layers: pd.Series, aoi_selection
) -> pd.Series:
    """
    Filter contextual layer by spatial extent. All AOIs in selection intersect the layer
    for valid comparison.

    Returns both filtered down layers per dataset, and a set of all removed layers
    to inform the agent.
    """

    aoi_bboxes = [box(*aoi["bbox"]) for aoi in aoi_selection["aois"]]
    removed_layers = []
    extent_filter_reason = "Selected area(s) of interest outside extent of layer."

    def _filter_context_layers(
        context_layers: list[dict],
    ) -> Union[pd.Series, pd.DataFrame]:
        if context_layers is None:
            return None

        filtered_layers = []
        for layer in context_layers:
            extent = layer.get("extent")

            # no extent defined, assume global
            if not extent:
                filtered_layers.append(layer)
            else:
                extent_geom = box(*extent)
                if all(
                    [
                        aoi_bbox.intersects(extent_geom)
                        for aoi_bbox in aoi_bboxes
                    ]
                ):
                    filtered_layers.append(layer)
                else:
                    removed_layers.append(
                        {"layer_name": layer, "reason": extent_filter_reason}
                    )
        return filtered_layers

    filtered_layers = context_layers.apply(_filter_context_layers)

    # get df of unique contextual layers
    removed_df = pd.DataFrame(removed_layers).drop_duplicates(
        subset="layer_name"
    )

    return filtered_layers, removed_df
