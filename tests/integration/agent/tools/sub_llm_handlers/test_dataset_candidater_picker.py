import sys
from pathlib import Path

import pytest

from src.agent.tools.sub_llm_handlers.dataset_candidate_picker import (
    DatasetCandidatePicker,
)
from src.shared.config import SharedSettings


pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture(scope="session", autouse=True)
def reset_retriever_cache():
    picker_module = sys.modules[
        "src.agent.tools.sub_llm_handlers.dataset_candidate_picker"
    ]
    picker_module.retriever_cache = None
    yield
    picker_module.retriever_cache = None


@pytest.fixture(scope="session")
def picker() -> DatasetCandidatePicker:
    embeddings_db_path = Path("data") / SharedSettings.dataset_embeddings_db
    if not embeddings_db_path.exists():
        pytest.skip(
            f"Local embeddings DB not found at {embeddings_db_path}"
        )
    return DatasetCandidatePicker()


async def test_dataset_candidate_picker_returns_k_candidate_datasets(
    picker: DatasetCandidatePicker,
):
    result = await picker.rag_candidate_datasets(
        "Show me annual tree cover loss in Brazil", k=3
    )

    assert len(result) == 3
    assert {"dataset_id", "dataset_name", "description"}.issubset(
        result.columns
    )
