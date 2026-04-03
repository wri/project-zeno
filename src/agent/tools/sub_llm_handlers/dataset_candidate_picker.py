from pathlib import Path

import pandas as pd
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from src.agent.tools.datasets_config import DATASETS
from src.shared.config import SharedSettings
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

data_dir = Path("data")

retriever_cache = None


class DatasetCandidatePicker:
    async def rag_candidate_datasets(self, query: str, k=3):
        logger.debug(f"Retrieving candidate datasets for query: '{query}'")
        candidate_datasets = []
        retriever = await self._get_retriever()
        match_documents = await retriever.ainvoke(query)
        for doc in match_documents:
            data = [ds for ds in DATASETS if ds["dataset_id"] == int(doc.id)]
            if not data:
                raise ValueError(f"No data found for dataset ID: {doc.id}")
            candidate_datasets.append(data[0])

        logger.debug(f"Found {len(candidate_datasets)} candidate datasets.")
        return pd.DataFrame(candidate_datasets)

    @staticmethod
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
