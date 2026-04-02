import sys

import pandas as pd
import pytest

from src.agent.tools.datasets_config import DATASETS
from src.agent.tools.models.dataset_selection_result import (
    DatasetSelectionResult,
)
from src.agent.tools.sub_llm_handlers.dataset_selector import DatasetSelector


pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture(scope="session", autouse=True)
def reset_small_model_client():
    llms_module = sys.modules["src.agent.llms"]
    llms_module.SMALL_MODEL = llms_module.get_small_model()
    yield


@pytest.fixture(scope="session")
def selector() -> DatasetSelector:
    return DatasetSelector()


@pytest.fixture(scope="session")
def candidate_datasets() -> pd.DataFrame:
    dataset_ids = {4, 5, 8}
    return pd.DataFrame(
        [dataset for dataset in DATASETS if dataset["dataset_id"] in dataset_ids]
    )


async def test_dataset_selector_returns_one_best_dataset_result(
    selector: DatasetSelector,
    candidate_datasets: pd.DataFrame,
):
    result = await selector.select_best_dataset(
        "What percent of 2000 forest did Kalimantan Barat lose from 2001 through 2024?",
        candidate_datasets,
    )

    assert isinstance(result, DatasetSelectionResult)
    assert result.dataset_id == 4
    assert result.dataset_name == "Tree cover loss"
    assert result.context_layer is None


async def test_dataset_selector_returns_option_other_than_first(
    selector: DatasetSelector,
    candidate_datasets: pd.DataFrame,
):
    result = await selector.select_best_dataset(
        "What percent of 2000 forest did Kalimantan Barat regrow from 2001 through 2024?",
        candidate_datasets,
    )

    assert isinstance(result, DatasetSelectionResult)
    assert result.dataset_id == 5
    assert result.dataset_name == "Tree cover gain"
    assert result.context_layer is None


async def test_dataset_selector_returns_contextual_layer(
    selector: DatasetSelector,
    candidate_datasets: pd.DataFrame,
):
    result = await selector.select_best_dataset(
        "What percent of 2000 natural forest did Kalimantan Barat lose from 2001 through 2024?",
        candidate_datasets,
    )

    assert isinstance(result, DatasetSelectionResult)
    assert result.dataset_id == 4
    assert result.dataset_name == "Tree cover loss"
    assert result.context_layer == "primary_forest"


async def test_dataset_selector_aoi_outside_contextual_layer_extent(
    selector: DatasetSelector,
    candidate_datasets: pd.DataFrame,
):
    result = await selector.select_best_dataset(
        "What percent of 2000 natural forest did British Columbia, Canada lose from 2001 through 2024?",
        candidate_datasets,
    )

    assert isinstance(result, DatasetSelectionResult)
    assert result.dataset_id == 4
    assert result.dataset_name == "Tree cover loss"
    assert result.context_layer is None
