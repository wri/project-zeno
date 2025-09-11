from pathlib import Path
from typing import Annotated, Optional

import pandas as pd
import yaml
from langchain_core.messages import ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_openai import OpenAIEmbeddings
from langgraph.types import Command
from pydantic import BaseModel, Field

from src.utils.llms import MODEL
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

data_dir = Path("data")

_retriever_cache = {}


ANALYTICS_DATASETS_PATH = Path(__file__).parent / "analytics_datasets.yml"
with open(ANALYTICS_DATASETS_PATH) as f:
    DATASETS = yaml.safe_load(f)["datasets"]


async def _get_openai_retriever():
    if "openai" not in _retriever_cache:
        logger.debug("Loading OpenAI retriever for the first time...")
        openai_embeddings = OpenAIEmbeddings(model="text-embedding-3-large")
        openai_index = InMemoryVectorStore.load(
            data_dir / "zeno-docs-openai-index-v2", embedding=openai_embeddings
        )
        _retriever_cache["openai"] = openai_index.as_retriever(
            search_type="similarity", search_kwargs={"k": 3}
        )
    return _retriever_cache["openai"]


async def rag_candidate_datasets(query: str, k=3, strategy="openai"):
    logger.debug(
        f"Retrieving candidate datasets for query: '{query}' using strategy: '{strategy}'"
    )
    candidate_datasets = []
    match strategy:
        case "openai":
            openai_retriever = await _get_openai_retriever()
            match_documents = await openai_retriever.ainvoke(query)
            for doc in match_documents:
                data = [
                    ds for ds in DATASETS if ds["dataset_id"] == int(doc.id)
                ]
                if not data:
                    raise ValueError(f"No data found for dataset ID: {doc.id}")
                candidate_datasets.append(data[0])
        case _:
            logger.error(f"Unknown RAG strategy: {strategy}")
            raise ValueError(f"Unknown strategy: {strategy}")

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

    IMPORTANT: Provide the selection reason in the same language used in the user query.

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
        DATASET_SELECTION_PROMPT | MODEL.with_structured_output(DatasetOption)
    )
    selection_result = await dataset_selection_chain.ainvoke(
        {
            "candidate_datasets": candidate_datasets[
                [
                    "dataset_id",
                    "dataset_name",
                    "description",
                    "content_date",
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
    query: str, tool_call_id: Annotated[str, InjectedToolCallId] = None
) -> Command:
    """
    Given a user query, runs RAG to retrieve relevant datasets, selects the best matching dataset with reasoning,
    and extracts relevant metadata needed for downstream querying.
    """
    logger.info("PICK-DATASET-TOOL")
    # Step 1: RAG lookup
    candidate_datasets = await rag_candidate_datasets(
        query, k=3, strategy="openai"
    )

    # Step 2: LLM to select best dataset and potential context layer
    selection_result = await select_best_dataset(query, candidate_datasets)

    tool_message = f"""Selected dataset: {selection_result.dataset_name}\nContext layer: {selection_result.context_layer}\nReasoning: {selection_result.reason}"""

    logger.debug(f"Pick dataset tool message: {tool_message}")

    return Command(
        update={
            "dataset": selection_result.model_dump(),
            "messages": [ToolMessage(tool_message, tool_call_id=tool_call_id)],
        },
    )
