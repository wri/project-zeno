from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Optional

import pandas as pd
from langchain_core.messages import ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langgraph.types import Command
from pydantic import BaseModel, Field, field_validator, model_validator

from src.agent.llms import SMALL_MODEL
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


def _resolve_params(
    selected: dict[str, Any], param_defs: dict
) -> dict[str, Any]:
    """Validate LLM-selected params against the dataset's param definitions.

    For each defined param:
    - If the LLM provided a value, validate it against allowed values.
    - If not provided (or invalid), use the default from the definition.
    - For list-type params, wrap scalars and filter invalid items.
    - Unknown params (not in definitions) are silently dropped.
    """
    validated: dict[str, Any] = {}
    for param_name, param_def in param_defs.items():
        allowed = param_def.get("values", [])
        default = param_def.get("default")
        is_list = param_def.get("type") == "list"

        if default == "all" and is_list:
            default = list(allowed)

        if param_name in selected:
            value = selected[param_name]
            if is_list:
                if not isinstance(value, list):
                    value = [value] if value else []
                valid_items = [v for v in value if v in allowed]
                validated[param_name] = (
                    valid_items
                    if valid_items
                    else (default if default is not None else [])
                )
            else:
                if value in allowed or value is None:
                    validated[param_name] = value
                else:
                    validated[param_name] = default
        else:
            if default is not None:
                validated[param_name] = default

    return validated


class DatasetOption(BaseModel):
    dataset_id: int = Field(
        description="ID of the dataset that best matches the user query."
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Selected parameter values for the dataset query. "
            "Keys are parameter names, values are the selected values. "
            "Only include params you want to override from their defaults."
        ),
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
    def validate_params_for_dataset(self) -> "DatasetOption":
        """Validate and normalize params against the dataset's config."""
        dataset_id = self.dataset_id
        if dataset_id is None:
            self.params = {}
            return self

        selected_dataset = next(
            (ds for ds in DATASETS if ds["dataset_id"] == dataset_id),
            None,
        )
        if not selected_dataset:
            self.params = {}
            return self

        config = selected_dataset.get("analytics_config") or {}
        param_defs = config.get("params") or {}
        self.params = _resolve_params(self.params, param_defs)
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


def _format_params_for_prompt(cfg: dict | None) -> str | None:
    """Format params for the LLM selection prompt."""
    if not cfg or not isinstance(cfg, dict):
        return None
    param_defs = cfg.get("params")
    if not param_defs:
        return None
    parts = []
    for name, defn in param_defs.items():
        vals = defn.get("values", [])
        default = defn.get("default")
        desc = defn.get("description", "")
        parts.append(
            f"{name}: values={vals}, default={default}, description={desc}"
        )
    return "; ".join(parts)


async def select_best_dataset(
    query: str, candidate_datasets: pd.DataFrame
) -> DatasetSelectionResult:
    DATASET_SELECTION_PROMPT = ChatPromptTemplate.from_messages(
        [
            (
                "user",
                """Based on the query, return the ID of the dataset that can best answer the
    user query and provide reason why it is the best match. Always return at least one dataset.
    Use all information provided to decide which dataset is the best match, especially the selection hints.

    Select parameter values from the dataset's available_params if relevant for the user query.
    Parameters allow filtering and configuring the dataset query. For example:
    - If a user asks "show me primary forest loss", set forest_filter to "primary_forest".
    - If a user asks "show me disturbance alerts by driver", set intersections to "driver".
    - If a user asks about a specific crop emission factor, set crop_types to that crop.
    Only include params you want to change from their defaults. The values you select MUST
    appear in the allowed values list — do not invent values.

    Evaluate if the best dataset is available for the date range requested by the user,
    if not, pick the closest date range but warn the user that there
    is not an exact match with the query requested by the user in the reason field.

    Pick the most granular dataset that matches the query and requested time range if specified.
    For instance, dont select tree cover loss by driver if the user requests a specific time range,
    pick tree cover loss instead.

    Keep explanations concise. Do not use dataset IDs to describe the dataset.
    For instance, instead of saying "Dataset ID: 123", say "Dataset: Tree Cover Loss".

    Use the language of the user query to generate the reason.

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
    prompt_df = candidate_datasets[
        [
            "dataset_id",
            "dataset_name",
            "description",
            "selection_hints",
            "content_date",
        ]
    ].copy()
    prompt_df["available_params"] = candidate_datasets[
        "analytics_config"
    ].apply(_format_params_for_prompt)

    selection_result = await dataset_selection_chain.ainvoke(
        {
            "candidate_datasets": prompt_df.to_csv(index=False),
            "user_query": query,
        }
    )
    logger.debug(
        f"Selected dataset ID: {selection_result.dataset_id}. "
        f"params={selection_result.params}. "
        f"Reason: {selection_result.reason}"
    )

    selected_row = candidate_datasets[
        candidate_datasets.dataset_id == selection_result.dataset_id
    ].iloc[0]

    return DatasetSelectionResult(
        dataset_id=selected_row.dataset_id,
        dataset_name=selected_row.dataset_name,
        params=selection_result.params,
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

    tool_message = f"""# About the selection
    Selected dataset name: {selection_result.dataset_name}
    Selected params: {selection_result.params}
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

    selected_dataset = [
        ds
        for ds in DATASETS
        if ds["dataset_id"] == selection_result.dataset_id
    ][0]
    tile_cfg = selected_dataset.get("tile_url_config", {})
    url_type = tile_cfg.get("type", "none")

    if url_type == "append_date_range":
        selection_result.tile_url += (
            f"&start_date={start_date}&end_date={end_date}"
        )
    elif url_type == "format_year":
        yr_range = tile_cfg.get("valid_year_range", [])
        fallback = tile_cfg.get("fallback_year")
        if yr_range and end_date.year in range(yr_range[0], yr_range[1] + 1):
            selection_result.tile_url = selection_result.tile_url.format(
                year=end_date.year
            )
        else:
            selection_result.tile_url = selection_result.tile_url.format(
                year=fallback
            )
    elif url_type == "append_year_range":
        yr_range = tile_cfg.get("valid_year_range", [])
        fb = tile_cfg.get("fallback", {})
        if yr_range and end_date.year in range(yr_range[0], yr_range[1] + 1):
            selection_result.tile_url += (
                f"&start_year={start_date.year}&end_year={end_date.year}"
            )
        else:
            selection_result.tile_url += (
                f"&start_year={fb['start_year']}&end_year={fb['end_year']}"
            )

    return Command(
        update={
            "dataset": selection_result.model_dump(),
            "messages": [ToolMessage(tool_message, tool_call_id=tool_call_id)],
        },
    )
