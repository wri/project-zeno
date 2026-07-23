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
    INTEGRATED_ALERTS_ID,
    LAND_COVER_CHANGE_ID,
    TREE_COVER_ID,
    TREE_COVER_LOSS_BY_DRIVER_ID,
    TREE_COVER_LOSS_BY_FIRES_ID,
    TREE_COVER_LOSS_ID,
)
from src.agent.i18n import t
from src.agent.language import (
    DEFAULT_LANGUAGE,
    language_name,
    resolve_language,
)
from src.agent.llms import SMALL_MODEL
from src.agent.subagents.pick_dataset.prompts import DATASET_SELECTOR_PROMPT
from src.agent.subagents.pick_dataset.schema import (
    ContextLayer,
    DatasetSelectionResponse,
    DatasetSelectionResult,
)
from src.agent.subagents.progress import emit_progress
from src.agent.tool_spec import ToolCategory, ToolSpec
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
    names = [ds["dataset_name"] for ds in candidate_datasets]
    emit_progress(
        "pick_dataset",
        "shortlist",
        f"Shortlisted {len(names)} candidate(s): {', '.join(names)}",
    )
    return pd.DataFrame(candidate_datasets)


SELECTION_RULES = """- Only choose a dataset if it can usefully answer ALL parts of the user's question.
- If no candidate can do that, return dataset_id as null and explain in the reason field what data we do have and why it falls short.
- Use the selection hints above — they are the primary signal for which dataset fits.
- Select a context layer when its description matches the query (pre-filtered to the AOI).
- Select parameters only when relevant; use only values listed in the dataset.
- If the user specifies a date range or time granularity (e.g. monthly, a specific year, daily alerts), only select a dataset if it genuinely supports that.
- Pick the most granular dataset/context layer/parameters that matches the query.
- Keep explanations concise. Do not reference dataset IDs."""


def _format_selection_hints(candidate_datasets: pd.DataFrame) -> str:
    lines = []
    for _, row in candidate_datasets.iterrows():
        hints = (row.get("selection_hints") or "").strip()
        if hints:
            lines.append(f"{row['dataset_name']}:\n{hints}")
    return "\n\n".join(lines) if lines else ""


async def select_best_dataset(
    query: str,
    candidate_datasets: pd.DataFrame,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    aoi_selection=None,
    language: str = DEFAULT_LANGUAGE,
) -> DatasetSelectionResponse:
    DATASET_SELECTION_PROMPT = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                DATASET_SELECTOR_PROMPT.format(
                    language=language_name(language)
                ),
            ),
            (
                "user",
                """## When to prefer each candidate dataset

{selection_hints}

## Rules

{rules}

## Candidate datasets

{candidate_datasets}

## User query

{user_query}

## Removed contextual layers

{removed_layers}

## Reminder: when to prefer each candidate dataset

{selection_hints}

## Reminder: rules

{rules}
""",
            ),
        ]
    )

    logger.debug("Invoking dataset selection chain...")
    dataset_selection_chain = (
        DATASET_SELECTION_PROMPT
        | SMALL_MODEL.with_structured_output(DatasetSelectionResponse)
    )

    if aoi_selection is None:
        removed_df = None
    else:
        filtered_layers, removed_layers = get_filtered_contextual_layers(
            candidate_datasets["context_layers"], aoi_selection
        )

        candidate_datasets["context_layers"] = filtered_layers
        removed_df = removed_layers.to_csv(index=False)

    selection_hints = _format_selection_hints(candidate_datasets)

    return await dataset_selection_chain.ainvoke(
        {
            "candidate_datasets": candidate_datasets[
                CANDIDATE_DATASET_REQUIRED_COLUMNS
            ].to_csv(index=False),
            "user_query": query,
            "removed_layers": removed_df,
            "selection_hints": selection_hints,
            "rules": SELECTION_RULES,
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
        language: str = DEFAULT_LANGUAGE,
    ) -> Command:
        """Resolve a request to the best dataset and update state."""
        logger.info("DATASET-SELECTOR: resolving query")

        # Step 1: RAG lookup of candidate datasets
        candidate_datasets = await rag_candidate_datasets(query, k=5)
        # Step 2: LLM picks the best dataset and context layer
        selection_result = await select_best_dataset(
            query,
            candidate_datasets,
            start_date,
            end_date,
            aoi_selection,
            language=language,
        )

        if selection_result.selected_dataset is None:
            if selection_result.suggested_datasets:
                name_by_id = {
                    ds["dataset_id"]: ds["dataset_name"] for ds in DATASETS
                }
                reasons = "\n".join(
                    f"- {name_by_id.get(o.dataset_id, str(o.dataset_id))}: {o.reason}"
                    for o in selection_result.suggested_datasets
                )
                intro = await t(
                    "pick_dataset.no_single_match",
                    language,
                    reason=selection_result.reason,
                )
                options_header = await t(
                    "pick_dataset.closest_options_header", language
                )
                tool_message = f"{intro}\n\n{options_header}\n{reasons}"
                return Command(
                    update={
                        "suggested_datasets": [
                            {
                                **o.model_dump(),
                                "dataset_name": name_by_id[o.dataset_id],
                            }
                            for o in selection_result.suggested_datasets
                        ],
                        "messages": [
                            ToolMessage(
                                tool_message,
                                tool_call_id=tool_call_id,
                                status="success",
                                response_metadata={
                                    "msg_type": "human_feedback"
                                },
                            )
                        ],
                    }
                )
            else:
                return Command(
                    update={
                        "messages": [
                            ToolMessage(
                                await t(
                                    "pick_dataset.no_match",
                                    language,
                                    reason=selection_result.reason,
                                ),
                                tool_call_id=tool_call_id,
                            )
                        ]
                    }
                )

        option = selection_result.selected_dataset

        logger.debug(
            f"Selected dataset ID: {option.dataset_id}. "
            f"context_layer={option.context_layer!r} (type={type(option.context_layer).__name__}). "
            f"Reason: {option.reason}"
        )

        selected_row = candidate_datasets[
            candidate_datasets.dataset_id == option.dataset_id
        ].iloc[0]

        effective_start_date, effective_end_date, _ = await revise_date_range(
            start_date,
            end_date,
            selected_row.dataset_id,
            option.context_layer,
        )
        dataset_tile_url, context_layers = get_tile_services_for_dataset(
            option,
            selected_row,
            effective_start_date,
            effective_end_date,
        )

        dataset_result = DatasetSelectionResult(
            dataset_id=selected_row.dataset_id,
            dataset_name=selected_row.dataset_name,
            context_layer=option.context_layer,
            parameters=option.parameters,
            start_date=effective_start_date,
            end_date=effective_end_date,
            reason=option.reason,
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
    # state["language"] should already carry the turn's resolved language
    # (see src.agent.language.resolve_language, set in chat.py); detecting
    # from `query` here is a fallback for callers that invoke this subagent
    # standalone, without going through that per-turn resolution.
    language = (
        state.get("language")
        or resolve_language(query=query)
        or DEFAULT_LANGUAGE
    )
    return await DatasetSelector().resolve(
        query,
        aoi_selection=state.get("aoi_selection"),
        start_date=start_date,
        end_date=end_date,
        tool_call_id=tool_call_id,
        language=language,
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

    if (
        selected_row.dataset_id == TREE_COVER_LOSS_ID
        or selected_row.dataset_id == TREE_COVER_LOSS_BY_FIRES_ID
    ):
        if end_date.year in range(2001, 2026):
            tile_url += (
                f"&start_year={start_date.year}&end_year={end_date.year}"
            )
        else:
            tile_url += "&start_year=2001&end_year=2025"
    elif selection_result.dataset_id in [DIST_ALERT_ID, INTEGRATED_ALERTS_ID]:
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


SPEC = ToolSpec(
    tool=pick_dataset,
    category=ToolCategory.SUBAGENT,
    prompt_fragment="- pick_dataset(query): dataset-selection subagent. Picks the dataset, context layer and date range that best answer the request. May return no dataset if none is a good fit — in that case relay its explanation and closest alternatives to the user; do not proceed to pull_data. Call it again whenever the user changes the dataset, context layer or parameters.",
)
