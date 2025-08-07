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
from langgraph.prebuilt import create_react_agent
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
            data_dir / "zeno-docs-openai-index", embedding=openai_embeddings
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


def select_best_dataset(query: str, candidate_datasets: pd.DataFrame):
    class DatasetOption(BaseModel):
        id: int = Field(
            description="ID of the dataset that best matches the user query."
        )
        reason: str = Field(
            description="Short reason why the dataset is the best match."
        )

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
                    "funcion_notes",
                    "date",
                    "context_layer",
                ]
            ].to_csv(index=False),
            "user_query": query,
        }
    )
    logger.debug(
        f"Selected dataset ID: {selection_result.id}. Reason: {selection_result.reason}"
    )
    return selection_result


class DatasetInfo(BaseModel):
    dataset_id: int
    source: str
    data_layer: str
    tile_url: str
    context_layer: Optional[str] = Field(
        None,
        description="Pick a single context layer from the dataset if useful",
    )
    threshold: Optional[int] = None


def extract_dataset_info(query: str, selection_id: int):
    DATASET_PROMPT = ChatPromptTemplate.from_messages(
        [
            (
                "user",
                """Given the user query and the dataset - extract the relevant information from the dataset to pull data from source.

    Dataset:
    {dataset}

    User Query:
    {user_query}
    """,
            ),
        ]
    )

    logger.debug(
        f"Invoking dataset info extraction chain for dataset ID: {selection_id}"
    )
    dataset_chain = DATASET_PROMPT | SONNET.with_structured_output(DatasetInfo)
    dataset_row = zeno_data[zeno_data.dataset_id == selection_id].iloc[0]
    final_info = dataset_chain.invoke(
        {
            "user_query": query,
            "dataset": dataset_row.to_json(),
        }
    )
    logger.debug(f"Extracted dataset info: {final_info}")
    return final_info


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

    # Step 2: LLM to select best dataset
    selection_result = select_best_dataset(query, candidate_datasets)

    # Step 3: LLM to extract structured info for downstream query
    dataset_info = extract_dataset_info(query, selection_result.id)

    tool_message = f"""Selected dataset: {dataset_info.data_layer}\nContext layer: {dataset_info.context_layer}\nTile URL: {dataset_info.tile_url}\nThreshold: {dataset_info.threshold}\nReasoning: {selection_result.reason}"""

    logger.debug(f"Pick dataset tool message: {tool_message}")

    return Command(
        update={
            "dataset": dataset_info.model_dump(),
            "messages": [ToolMessage(tool_message, tool_call_id=tool_call_id)],
        },
    )


if __name__ == "__main__":
    agent = create_react_agent(
        SONNET,
        tools=[pick_dataset],
        prompt="""You are a Data Agent that can ONLY HELP PICK a dataset using the `pick-dataset` tool.

        {instructions}
        """,
    )

    user_queries = [
        "find threats to tigers in kbas of Odisha",
        "Show me forest data for congo not drc",
        "What is the deforestation rate in Ontario last year?",
        "I need urgent data on ilegal logging in Borgou!!",
        "How much tree cover has been lost in Sumatera since 2000?",
        "find threats to tigers in Simlipal Park",
        "find deforestation rate in Amazon",
        "find crocodile statistics in Satkosia Gorge",
        "find deforestation rate in PNG",
    ]

    for query in user_queries[:1]:
        for step in agent.stream(
            {"messages": [{"role": "user", "content": query}]},
            stream_mode="values",
        ):
            message = step["messages"][-1]
            if isinstance(message, tuple):
                logger.info(message)
            else:
                message.pretty_print()
