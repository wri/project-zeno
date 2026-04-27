from datetime import date, datetime
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
from shapely import box

from src.agent.llms import SMALL_MODEL
from src.agent.tools.data_handlers.analytics_handler import (
    DIST_ALERT_ID,
    FOREST_CARBON_FLUX_ID,
    GRASSLANDS_ID,
    LAND_COVER_CHANGE_ID,
    TREE_COVER_ID,
    TREE_COVER_LOSS_BY_DRIVER_ID,
    TREE_COVER_LOSS_ID,
)
from src.agent.tools.datasets_config import (
    CANDIDATE_DATASET_REQUIRED_COLUMNS,
    DATASETS,
)
from src.agent.tools.pick_dataset.schema import (
    ContextLayer,
    DatasetOption,
    DatasetSelectionResult,
)
from src.agent.tools.util import revise_date_range
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


async def select_best_dataset(
    query: str,
    candidate_datasets: pd.DataFrame,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    aoi_selection=None,
) -> DatasetSelectionResult:
    DATASET_SELECTION_PROMPT = ChatPromptTemplate.from_messages(
        [
            (
                "user",
                """Based on the query, return the ID of the dataset that can best answer the
    user query and provide reason why it is the best match. Always return at least one dataset.
    Use all information provided to decide which dataset is the best match, especially the selection hints.

    After selecting the best dataset, inspect its filtered_context_layers. Choose the single context layer whose description 
    best fits the user's query, even when the user does not name the layer directly. Context layers differentiate types of 
    data within the same dataset, and their descriptions are guidance for when each layer applies. If no context layer fits the query, return null.

    After selecting the best context layer or null, select parameters and values if they are relevant or specified in the user query. Parameters allow further filtering
    the analysis to better answer the query. Select only values listed in the value field for a parameter. For example,
    if a user says "show me tree cover loss in forests where canopy cover is greater than 50%", you may select the parameter canopy cover
    and value 50.

    Evaluate if the best dataset is available for the date range requested by the user.
    If not, pick the closest available date range and include a warning in the dataset pick reason.

    Pick the most granular dataset/contextual layer/parameters that matches the query.

    Keep explanations concise. Do not use datset IDs to describe the dataset.
    For instance, instead of saying "Dataset ID: 123", say "Dataset: Tree Cover Loss".

    Use the language of the user query to generate the reason, not the language of any place mentioned in the query.

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
        removed_df = None
    else:
        filtered_layers, removed_layers = get_filtered_contextual_layers(
            candidate_datasets["context_layers"], aoi_selection
        )

        candidate_datasets["context_layers"] = filtered_layers
        removed_df = removed_layers.to_csv(index=False)

    selection_result = await dataset_selection_chain.ainvoke(
        {
            "candidate_datasets": candidate_datasets[
                CANDIDATE_DATASET_REQUIRED_COLUMNS
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

    effective_start_date, effective_end_date, _ = await revise_date_range(
        start_date, end_date, selected_row.dataset_id
    )
    dataset_tile_url, context_layers = get_tile_services_for_dataset(
        selection_result,
        selected_row,
        effective_start_date,
        effective_end_date,
    )

    return DatasetSelectionResult(
        dataset_id=selected_row.dataset_id,
        dataset_name=selected_row.dataset_name,
        context_layer=selection_result.context_layer,
        parameters=selection_result.parameters,
        reason=selection_result.reason,
        tile_url=dataset_tile_url,
        analytics_api_endpoint=selected_row.analytics_api_endpoint,
        description=selected_row.description,
        prompt_instructions=selected_row.prompt_instructions,
        methodology=selected_row.methodology,
        cautions=selected_row.cautions,
        function_usage_notes=selected_row.function_usage_notes,
        citation=selected_row.citation,
        content_date=selected_row.content_date,
        selection_hints=selected_row.selection_hints,
        code_instructions=selected_row.code_instructions,
        presentation_instructions=selected_row.presentation_instructions,
        context_layers=context_layers,
    )


@tool("pick_dataset")
async def pick_dataset(
    query: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    state: Annotated[Dict, InjectedState] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
) -> Command:
    """
    Given a user query, runs RAG to retrieve relevant datasets, selects the best matching dataset within the specified time range with reasoning,
    and extracts relevant metadata needed for downstream querying such as context layers and parameters.

    If the user requests data with a different context layer or parameter, pick the dataset again.

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
        query, candidate_datasets, start_date, end_date, aoi_selection
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
    extent_filter_reason = (
        "Selected area(s) of interest outside extent of layer."
    )

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


def get_tile_services_for_dataset(
    selection_result, selected_row, start_date, end_date
):
    context_layers = []
    tile_url = selected_row.tile_url
    start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_date = datetime.strptime(end_date, "%Y-%m-%d").date()

    if not selected_row.tile_url.startswith("http"):
        tile_url = SharedSettings.eoapi_base_url + tile_url

    if (
        selection_result.context_layer
        and selected_row.context_layers is not None
    ):
        selected_context_layer = next(
            (
                x
                for x in selected_row.context_layers
                if x["value"] == selection_result.context_layer
            ),
            None,
        )
        context_layer = ContextLayer(
            name=selected_context_layer.get("value"),
            tile_url=selected_context_layer.get("tile_url"),
        )
        context_layers.append(context_layer)

    if selected_row.dataset_id in [
        TREE_COVER_LOSS_ID,
        TREE_COVER_ID,
        TREE_COVER_LOSS_BY_DRIVER_ID,
        FOREST_CARBON_FLUX_ID,
    ]:
        canopy_cover = 30
        if selection_result.parameters is not None:
            for param in selection_result.parameters:
                if param.name == "canopy_cover":
                    canopy_cover = max(param.values)

        if selected_row.dataset_id != TREE_COVER_ID:
            canopy_cover_tile_url = next(
                (
                    param["tile_url"]
                    for param in selected_row.parameters
                    if param["name"] == "canopy_cover"
                ),
                None,
            )

            thresholded_tile_url = canopy_cover_tile_url.replace(
                "{threshold}", str(canopy_cover)
            )

            context_layer = ContextLayer(
                name="canopy_cover",
                tile_url=thresholded_tile_url,
            )
            context_layers.append(context_layer)

        tile_url = selected_row.tile_url.replace(
            "{threshold}", str(canopy_cover)
        )

    if selected_row.dataset_id == TREE_COVER_LOSS_ID:
        if end_date.year in range(2001, 2025):
            tile_url += (
                f"&start_year={start_date.year}&end_year={end_date.year}"
            )
        else:
            tile_url += "&start_year=2001&end_year=2025"
    elif selection_result.dataset_id == DIST_ALERT_ID:
        tile_url += f"&start_date={start_date}&end_date={end_date}"
    elif selection_result.dataset_id in [LAND_COVER_CHANGE_ID, GRASSLANDS_ID]:
        if end_date.year in range(2000, 2023):
            tile_url = tile_url.format(year=end_date.year)
        else:
            tile_url = tile_url.format(year="2022")

    return tile_url, context_layers


def get_dates_for_dataset(
    selection_result, selected_row, start_date, end_date
) -> tuple[str, str]:
    """Resolve missing dates from the selected dataset's own coverage."""
    dataset_start_date = selected_row.get("start_date")
    dataset_end_date = selected_row.get("end_date") or str(date.today())

    resolved_start_date = start_date or dataset_start_date
    resolved_end_date = end_date or dataset_end_date

    logger.debug(
        "Resolved dates for dataset %s (%s): start=%s end=%s",
        selection_result.dataset_id,
        selected_row.get("dataset_name"),
        resolved_start_date,
        resolved_end_date,
    )

    return resolved_start_date, resolved_end_date
