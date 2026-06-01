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

from src.agent.datasets.config import (
    CANDIDATE_DATASET_REQUIRED_COLUMNS,
    DATASETS,
)
from src.agent.datasets.dates import revise_date_range
from src.agent.datasets.handlers.analytics_handler import (
    DIST_ALERT_ID,
    FOREST_CARBON_FLUX_ID,
    GRASSLANDS_ID,
    LAND_COVER_CHANGE_ID,
    TREE_COVER_ID,
    TREE_COVER_LOSS_BY_DRIVER_ID,
    TREE_COVER_LOSS_BY_FIRES_ID,
    TREE_COVER_LOSS_ID,
)
from src.agent.llms import SMALL_MODEL
from src.agent.subagents.pick_dataset.prompts import DATASET_SELECTOR_PROMPT
from src.agent.subagents.pick_dataset.schema import (
    ContextLayer,
    DatasetScore,
    DatasetSelectionResult,
    ScoredSelectionResponse,
)
from src.agent.subagents.progress import emit_progress
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
            search_type="similarity", search_kwargs={"k": 5}
        )
    return retriever_cache


async def rag_candidate_datasets(query: str, k=5):
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
    names = [ds["dataset_name"] for ds in candidate_datasets]
    emit_progress(
        "pick_dataset",
        "shortlist",
        f"Shortlisted {len(names)} candidate(s): {', '.join(names)}",
    )
    return pd.DataFrame(candidate_datasets)


def apply_score_thresholds(
    scores: list[DatasetScore],
) -> tuple[Optional[DatasetScore], list[DatasetScore]]:
    """Deterministically apply selection thresholds to scored candidates.

    Returns (selected, suggestions) where:
      - selected: highest-scoring dataset if score >= 4, else None
      - suggestions: up to 3 datasets with score >= 2, excluding selected, sorted descending
    """
    sorted_scores = sorted(scores, key=lambda s: s.score, reverse=True)
    selected = (
        sorted_scores[0]
        if sorted_scores and sorted_scores[0].score >= 5
        else None
    )
    suggestions = [
        s
        for s in sorted_scores
        if s.score >= 3
        and (selected is None or s.dataset_id != selected.dataset_id)
    ][:3]
    return selected, suggestions


async def select_best_dataset(
    query: str,
    candidate_datasets: pd.DataFrame,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    aoi_selection=None,
) -> ScoredSelectionResponse:
    DATASET_SELECTION_PROMPT = ChatPromptTemplate.from_messages(
        [
            ("system", DATASET_SELECTOR_PROMPT),
            (
                "user",
                """Score every candidate dataset for the user query.

    For each dataset, award a score from 0-5 by answering these five questions.
    Award 1 if the dataset satisfies the question OR if the user did not ask for that dimension.
    Award 0 only if the user explicitly asked for it and the dataset does not support it.

    1. Is it relevant to the land cover / land use type the user is asking about?
    2. Does it cover the time range and temporal resolution the user needs? Score 0 if the user
       specified a start date that falls before the dataset's start_date, or an end date after the
       dataset's end_date, or a temporal resolution (e.g. annual, real-time) the dataset does not support.
    3. Does it have the measurement the user is asking for (area, carbon, alerts, etc.)?
    4. Does it represent the type of event or transition the user is asking about?
    5. Does it address driver or cause attribution if the user asked for it?

    For each dataset also select the best context layer (from filtered_context_layers) and parameters
    if relevant to the query. Context layers allow differentiating between different types of data within
    the same dataset — select one when its description matches the query.
    Select only parameter values listed in the dataset's value field.

    Keep reasons concise. Do not reference dataset IDs in reasons.

    Candidate datasets:

    {candidate_datasets}

    User query:

    {user_query}

    The following contextual layers cannot be picked right now:

    {removed_layers}

    """,
            ),
        ]
    )

    logger.debug("Invoking dataset scoring chain...")
    chain = DATASET_SELECTION_PROMPT | SMALL_MODEL.bind(
        temperature=0
    ).with_structured_output(ScoredSelectionResponse)

    if aoi_selection is None:
        removed_df = None
    else:
        filtered_layers, removed_layers = get_filtered_contextual_layers(
            candidate_datasets["context_layers"], aoi_selection
        )
        candidate_datasets["context_layers"] = filtered_layers
        removed_df = removed_layers.to_csv(index=False)

    return await chain.ainvoke(
        {
            "candidate_datasets": candidate_datasets[
                CANDIDATE_DATASET_REQUIRED_COLUMNS
            ].to_csv(index=False),
            "user_query": query,
            "removed_layers": removed_df,
        }
    )


class DatasetSelector:
    """Dataset-selection subagent: resolves a request to the best dataset.

    Used as a tool by the orchestrator via `pick_dataset`. The orchestrator
    passes the user's request; this subagent does its own reasoning — it
    retrieves candidate datasets, picks the best match with the selection LLM
    (driven by DATASET_SELECTOR_PROMPT), resolves the context layer and
    parameters, and clamps the date range to the dataset's real coverage.
    """

    async def resolve(
        self,
        query: str,
        aoi_selection=None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        tool_call_id: Optional[str] = None,
    ) -> Command:
        """Resolve a request to the best dataset and update state."""
        logger.info("DATASET-SELECTOR: resolving query")

        # Step 1: RAG lookup of candidate datasets
        candidate_datasets = await rag_candidate_datasets(query, k=5)
        # Step 2: LLM scores each candidate on 5 questions
        scored_response = await select_best_dataset(
            query, candidate_datasets, start_date, end_date, aoi_selection
        )
        # Step 3: deterministically apply thresholds
        selected_score, suggestions = apply_score_thresholds(
            scored_response.scores
        )

        if selected_score is None:
            name_by_id = {
                ds["dataset_id"]: ds["dataset_name"] for ds in DATASETS
            }
            if suggestions:
                reasons = "\n".join(
                    f"- {name_by_id.get(s.dataset_id, str(s.dataset_id))} (score {s.score}/5): {s.reason}"
                    for s in suggestions
                )
                tool_message = f"No dataset scored high enough to be selected. Here are the closest options:\n\n{reasons}"
                return Command(
                    update={
                        "suggested_datasets": [
                            {
                                "dataset_id": s.dataset_id,
                                "dataset_name": name_by_id.get(
                                    s.dataset_id, ""
                                ),
                                "reason": s.reason,
                            }
                            for s in suggestions
                        ],
                        "messages": [
                            ToolMessage(
                                tool_message, tool_call_id=tool_call_id
                            )
                        ],
                    }
                )
            else:
                top = (
                    scored_response.scores[0]
                    if scored_response.scores
                    else None
                )
                explanation = (
                    top.reason if top else "No candidates were relevant."
                )
                return Command(
                    update={
                        "messages": [
                            ToolMessage(
                                f"No relevant dataset found. {explanation}",
                                tool_call_id=tool_call_id,
                            )
                        ]
                    }
                )

        logger.debug(
            f"Selected dataset ID: {selected_score.dataset_id}. "
            f"context_layer={selected_score.context_layer!r}. "
            f"Score: {selected_score.score}/5. Reason: {selected_score.reason}"
        )

        selected_row = candidate_datasets[
            candidate_datasets.dataset_id == selected_score.dataset_id
        ].iloc[0]

        effective_start_date, effective_end_date, _ = await revise_date_range(
            start_date,
            end_date,
            selected_row.dataset_id,
            selected_score.context_layer,
        )
        dataset_tile_url, context_layers = get_tile_services_for_dataset(
            selected_score,
            selected_row,
            effective_start_date,
            effective_end_date,
        )

        dataset_result = DatasetSelectionResult(
            dataset_id=selected_row.dataset_id,
            dataset_name=selected_row.dataset_name,
            context_layer=selected_score.context_layer,
            parameters=selected_score.parameters,
            start_date=effective_start_date,
            end_date=effective_end_date,
            reason=selected_score.reason,
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

        layer = dataset_result.context_layer
        emit_progress(
            "pick_dataset",
            "selected",
            f"Selected dataset: {dataset_result.dataset_name}"
            + (f" (context layer: {layer})" if layer else ""),
        )

        tool_message = f"""# About the selection
    Selected dataset name: {dataset_result.dataset_name}
    Selected context layer: {dataset_result.context_layer}
    Reasoning for selection: {dataset_result.reason}

    # Additional dataset information

    ## Description

    {dataset_result.description}

    ## Function usage notes:

    {dataset_result.function_usage_notes}

    ## Usage cautions

    {dataset_result.cautions}

    ## Content date

    {dataset_result.content_date}
    """

        if dataset_result.presentation_instructions:
            tool_message += f"""
    ## Presentation instructions

    {dataset_result.presentation_instructions}
    """

        logger.debug(f"Pick dataset tool message: {tool_message}")

        return Command(
            update={
                "dataset": dataset_result.model_dump(),
                "suggested_datasets": [],
                "messages": [
                    ToolMessage(tool_message, tool_call_id=tool_call_id)
                ],
            },
        )


@tool("pick_dataset")
async def pick_dataset(
    query: str,
    state: Annotated[Dict, InjectedState],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Pick the dataset, context layer and date range that best answer the
    user's request — a dataset-selection subagent.

    Pass the user's request as `query`. The subagent retrieves candidate
    datasets, picks the best match, resolves the context layer/parameters and
    clamps the date range to what the dataset actually covers.

    - Dataset-only requests (e.g. "pick tcl by driver", "use tree cover loss
      by driver"): an AOI is NOT required — do not ask for a country/region,
      and do not call pick_aoi / pull_data / generate_insights unless the user
      asks for more. Briefly confirm the selection.
    - Re-pick: call this again before pull_data whenever the user changes the
      dataset, the context layer (drivers, land cover change, time dynamics,
      etc.) or parameters.
    - Optional start_date/end_date (YYYY-MM-DD) narrow the range; if they
      don't exactly match the dataset, the closest valid range is used.
    """
    return await DatasetSelector().resolve(
        query,
        aoi_selection=state.get("aoi_selection"),
        start_date=start_date,
        end_date=end_date,
        tool_call_id=tool_call_id,
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
        TREE_COVER_LOSS_BY_FIRES_ID,
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
        if end_date.year in range(2001, 2026):
            tile_url += (
                f"&start_year={start_date.year}&end_year={end_date.year}"
            )
        else:
            tile_url += "&start_year=2001&end_year=2025"
    elif selection_result.dataset_id == DIST_ALERT_ID:
        tile_url += f"&start_date={start_date}&end_date={end_date}"
    elif selection_result.dataset_id in [LAND_COVER_CHANGE_ID, GRASSLANDS_ID]:
        # Annual raster item in URL; start/end are already clamped to dataset YAML
        tile_url = tile_url.format(year=end_date.year)

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
