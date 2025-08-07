from pathlib import Path
from typing import Annotated, Optional

import pandas as pd
from langchain_core.messages import ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_ollama import OllamaEmbeddings
from langchain_openai import OpenAIEmbeddings
from langgraph.types import Command
from pydantic import BaseModel, Field
from pylate import indexes, models, retrieve

from src.utils.llms import SONNET
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

data_dir = Path("data")
zeno_data = pd.read_csv(data_dir / "zeno_data_clean_v2.csv")

_retriever_cache = {}


def _get_openai_retriever():
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


def _get_nomic_retriever():
    if "nomic" not in _retriever_cache:
        logger.debug("Loading Nomic retriever for the first time...")
        nomic_embeddings = OllamaEmbeddings(model="nomic-embed-text")
        nomic_index = InMemoryVectorStore.load(
            data_dir / "zeno-docs-nomic-index", embedding=nomic_embeddings
        )
        _retriever_cache["nomic"] = nomic_index.as_retriever(
            search_type="similarity", search_kwargs={"k": 3}
        )
    return _retriever_cache["nomic"]


def _get_colbert_retriever_and_model():
    if "colbert" not in _retriever_cache:
        logger.debug("Loading ColBERT model and index for the first time...")
        colbert_model = models.ColBERT(
            model_name_or_path="lightonai/GTE-ModernColBERT-v1"
        )
        colbert_index = indexes.PLAID(
            index_folder=data_dir / "colbert-index", index_name="dataset"
        )
        colbert_retriever = retrieve.ColBERT(index=colbert_index)
        _retriever_cache["colbert"] = (colbert_retriever, colbert_model)
    return _retriever_cache["colbert"]


def rag_candidate_datasets(query: str, k=3, strategy="openai"):
    logger.debug(
        f"Retrieving candidate datasets for query: '{query}' using strategy: '{strategy}'"
    )
    candidate_datasets = []
    match strategy:
        case "openai":
            openai_retriever = _get_openai_retriever()
            match_documents = openai_retriever.invoke(query)
            for doc in match_documents:
                metadata = doc.metadata.copy()
                metadata["description"] = doc.page_content
                candidate_datasets.append(metadata)
        case "nomic":
            nomic_retriever = _get_nomic_retriever()
            match_documents = nomic_retriever.invoke(query)
            for doc in match_documents:
                candidate_datasets.append(
                    zeno_data[zeno_data.dataset_id == int(doc.id)]
                    .iloc[0]
                    .to_dict()
                )
        case "colbert":
            colbert_retriever, colbert_model = (
                _get_colbert_retriever_and_model()
            )
            query_embedding = colbert_model.encode(
                query, batch_size=1, is_query=True, show_progress_bar=False
            )

            scores = colbert_retriever.retrieve(
                queries_embeddings=query_embedding, k=k
            )

            candidate_datasets = [
                zeno_data[zeno_data.dataset_id == int(score["id"])]
                .iloc[0]
                .to_dict()
                for score in scores[0]
            ]
        case _:
            logger.error(f"Unknown RAG strategy: {strategy}")
            raise ValueError(f"Unknown strategy: {strategy}")

    logger.debug(f"Found {len(candidate_datasets)} candidate datasets.")
    return pd.DataFrame(candidate_datasets)


class DatasetOption(BaseModel):
    dataset_id: int = Field(
        description="ID of the dataset that best matches the user query."
    )
    dataset_name: str = Field(
        description="Name of the dataset that best matches the user query."
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
        description="Tile URL of the dataset that best matches the user query."
    )


def select_best_dataset(query: str, candidate_datasets: pd.DataFrame):
    DATASET_SELECTION_PROMPT = ChatPromptTemplate.from_messages(
        [
            (
                "user",
                """Based on the query, return the ID of the dataset that can best answer the user query and provide reason why it is the best match.
    Look at the dataset description and contextual layers, as well as date & variables.

    Candidate datasets:

    {candidate_datasets}

    Query:

    {user_query}
    """,
            )
        ]
    )

    logger.debug("Invoking dataset selection chain...")
    dataset_selection_chain = (
        DATASET_SELECTION_PROMPT | SONNET.with_structured_output(DatasetOption)
    )
    selection_result = dataset_selection_chain.invoke(
        {
            "candidate_datasets": candidate_datasets[
                [
                    "dataset_id",
                    "dataset_name",
                    "description",
                    "date",
                    "context_layers",
                ]
            ].to_csv(index=False),
            "user_query": query,
        }
    )
    logger.debug(
        f"Selected dataset ID: {selection_result.dataset_id}. Reason: {selection_result.reason}"
    )

    return DatasetSelectionResult(
        dataset_id=selection_result.dataset_id,
        dataset_name=selection_result.dataset_name,
        context_layer=selection_result.context_layer,
        reason=selection_result.reason,
        tile_url=candidate_datasets[
            candidate_datasets.dataset_id == selection_result.dataset_id
        ]
        .iloc[0]
        .tile_url,
    )


@tool("pick-dataset")
def pick_dataset(
    query: str, tool_call_id: Annotated[str, InjectedToolCallId] = None
) -> Command:
    """
    Given a user query, runs RAG to retrieve relevant datasets, selects the best matching dataset with reasoning,
    and extracts relevant metadata needed for downstream querying.
    """
    logger.info("PICK-DATASET-TOOL")
    # Step 1: RAG lookup
    candidate_datasets = rag_candidate_datasets(query, k=3, strategy="openai")

    # Step 2: LLM to select best dataset and potential context layer
    selection_result = select_best_dataset(query, candidate_datasets)

    tool_message = f"""Selected dataset ID: {selection_result.dataset_id}\nContext layer: {selection_result.context_layer}\nReasoning: {selection_result.reason}"""

    logger.debug(f"Pick dataset tool message: {tool_message}")

    return Command(
        update={
            "dataset": selection_result.model_dump(),
            "messages": [ToolMessage(tool_message, tool_call_id=tool_call_id)],
        },
    )
