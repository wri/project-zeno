from pathlib import Path

from langchain_core.vectorstores import InMemoryVectorStore
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from src.shared.config import SharedSettings
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

data_dir = Path("data")


class DatasetRetriever:
    def __init__(
        self,
        embeddings_db,
        embeddings_model,
        embeddings_task_type,
        num_results,
    ):
        self.embeddings_db = embeddings_db
        self.embeddings_model = embeddings_model
        self.embeddings_task_type = embeddings_task_type
        self.num_results = num_results

    async def retrieve(self, query) -> list[int]:
        if self.retriever is None:
            self.retriever = self._get_retriever()

        match_docs = await self.retriever.ainvoke(query)
        match_dataset_ids = [doc.id for doc in match_docs]
        return match_dataset_ids

    async def _get_retriever(self):
        logger.debug("Loading retriever for the first time...")

        embeddings = GoogleGenerativeAIEmbeddings(
            model=self.embeddings_model,
            task_type=self.embeddings_task_type,
        )
        index = InMemoryVectorStore.load(
            data_dir / self.embeddings_db,
            embedding=embeddings,
        )
        retriever = index.as_retriever(
            search_type="similarity", search_kwargs={"k": self.num_results}
        )

        return retriever


dataset_retriever = DatasetRetriever(
    SharedSettings.dataset_embeddings_db,
    SharedSettings.dataset_embeddings_model,
    SharedSettings.dataset_embeddings_task_type,
    3,
)
