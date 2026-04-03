from pathlib import Path

import pandas as pd
from langchain_core.prompts import ChatPromptTemplate

from src.agent.llms import SMALL_MODEL
from src.agent.tools.models.dataset_option import DatasetOption
from src.agent.tools.models.dataset_selection_result import (
    DatasetSelectionResult,
)
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

data_dir = Path("data")

retriever_cache = None


class DatasetSelector:
    async def select_best_dataset(
        self, query: str, candidate_datasets: pd.DataFrame
    ) -> DatasetSelectionResult:
        DATASET_SELECTION_PROMPT = ChatPromptTemplate.from_messages(
            [
                (
                    "user",
                    """Based on the query, return the ID of the dataset that can best answer the
        user query and provide reason why it is the best match. Always return at least one dataset.
        Use all information provided to decide which dataset is the best match, especially the selection hints.

        Select a single context layer from the dataset if relevant for the user query. Context layers
        allow difrenciating between different types of data within the same dataset. So if a user asks
        to show something like "show me tree cover loss by driver", you should select a context layer

        Evaluate if the best dataset is available for the date range requested by the user,
        if not, pick the closest date range but warn the user that there
        is not an exact match with the query requested by the user in the reason field.

        Pick the most granular dataset that matches the query and requested time range if specified.
        For instance, dont select tree cover loss by driver if the user requests a specific time range,
        pick tree cover loss instead.

        Keep explanations concise. Do not use datset IDs to describe the dataset.
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
        selection_result = await dataset_selection_chain.ainvoke(
            {
                "candidate_datasets": candidate_datasets[
                    [
                        "dataset_id",
                        "dataset_name",
                        "description",
                        "selection_hints",
                        "content_date",
                        "context_layers",
                    ]
                ].to_csv(index=False),
                "user_query": query,
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
