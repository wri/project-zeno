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


@pytest.fixture(scope="session")
def aoi_bbox_context() -> list[dict]:
    return [
        {
            "name": "Kalimantan Barat, Indonesia",
            "source": "gadm",
            "src_id": "IDN.35_1",
            "bbox": [108.0, -3.5, 114.5, 1.5],
        }
    ]


async def test_dataset_selector_returns_one_best_dataset_result(
    selector: DatasetSelector,
    candidate_datasets: pd.DataFrame,
    aoi_bbox_context: list[dict],
):
    result = await selector.select_best_dataset(
        "What percent of 2000 forest did Kalimantan Barat lose from 2001 through 2024?",
        candidate_datasets,
        aoi_bbox_context=aoi_bbox_context,
    )

    assert isinstance(result, DatasetSelectionResult)
    assert result.dataset_id == 4
    assert result.dataset_name == "Tree cover loss"
    assert result.context_layer is None


async def test_dataset_selector_returns_option_other_than_first(
    selector: DatasetSelector,
    candidate_datasets: pd.DataFrame,
    aoi_bbox_context: list[dict],
):
    result = await selector.select_best_dataset(
        "What percent of 2000 forest did Kalimantan Barat regrow from 2001 through 2024?",
        candidate_datasets,
        aoi_bbox_context=aoi_bbox_context,
    )

    assert isinstance(result, DatasetSelectionResult)
    assert result.dataset_id == 5
    assert result.dataset_name == "Tree cover gain"
    assert result.context_layer is None


async def test_dataset_selector_returns_contextual_layer(
    selector: DatasetSelector,
    candidate_datasets: pd.DataFrame,
    aoi_bbox_context: list[dict],
):
    result = await selector.select_best_dataset(
        "What percent of 2000 natural forest did Kalimantan Barat lose from 2001 through 2024?",
        candidate_datasets,
        aoi_bbox_context=aoi_bbox_context,
    )

    assert isinstance(result, DatasetSelectionResult)
    assert result.dataset_id == 4
    assert result.dataset_name == "Tree cover loss"
    assert result.context_layer == "primary_forest"


async def test_dataset_selector_aoi_outside_contextual_layer_extent(
    selector: DatasetSelector,
    candidate_datasets: pd.DataFrame,
):
    british_columbia_bbox_context = [
        {
            "name": "British Columbia, Canada",
            "source": "gadm",
            "src_id": "CAN.2_1",
            "bbox": [-139.06, 48.25, -114.03, 60.01],
        }
    ]

    result = await selector.select_best_dataset(
        "What percent of 2000 natural forest did British Columbia, Canada lose from 2001 through 2024?",
        candidate_datasets,
        aoi_bbox_context=british_columbia_bbox_context,
    )

    assert isinstance(result, DatasetSelectionResult)
    assert result.dataset_id == 4
    assert result.dataset_name == "Tree cover loss"
    assert result.context_layer is None
