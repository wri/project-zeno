from src.agent.datasets.config import DATASETS
from src.agent.tools.analytics_mcp.catalog_datasets import CatalogDatasets

TREE_COVER_LOSS = 4
TREE_COVER_GAIN = 5


async def test_selection_keeps_a_context_layer_of_the_dataset():
    selection = await CatalogDatasets(DATASETS).selection(
        TREE_COVER_LOSS, "natural_forest", 15
    )

    assert selection["context_layer"] == "natural_forest"
    assert selection["parameters"][0]["values"] == [15]


async def test_selection_drops_a_context_layer_the_dataset_lacks():
    selection = await CatalogDatasets(DATASETS).selection(
        TREE_COVER_GAIN, "primary_forest"
    )

    assert selection["context_layer"] is None
