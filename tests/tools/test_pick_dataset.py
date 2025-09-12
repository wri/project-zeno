import uuid

import pytest
import requests

from src.tools.pick_dataset import pick_dataset


@pytest.fixture(scope="function", autouse=True)
def test_db():
    """Override the global test_db fixture to avoid database connections."""
    pass


@pytest.fixture(scope="function", autouse=True)
def test_db_session():
    """Override the global test_db_session fixture to avoid database connections."""
    pass


DIST_ALERT = "ecosystem disturbance alerts"
LAND_COVER_CHANGE = "land cover change"
GRASSLANDS = "grasslands"
NATURAL_LANDS = "natural lands"
TREE_COVER_LOSS = "tree cover loss"
TREE_COVER_GAIN = "tree cover gain"
CARBON_FLUX = "forest greenhouse gas net flux"
TREE_COVER = "tree cover"

lookup = {
    DIST_ALERT: 0,
    LAND_COVER_CHANGE: 1,
    GRASSLANDS: 2,
    NATURAL_LANDS: 3,
    TREE_COVER_LOSS: 4,
    TREE_COVER_GAIN: 5,
    CARBON_FLUX: 6,
    TREE_COVER: 7,
}


@pytest.fixture(
    params=[
        # Dataset 0 queries (Ecosystem disturbance alerts) - near-real-time vegetation changes
        (
            "Which year recorded more alerts within Protected Areas in Ucayali, Peru? 2023 or 2024?",
            DIST_ALERT,
        ),
        (
            "Show me recent vegetation disturbances in the Amazon basin over the past month",
            DIST_ALERT,
        ),
        (
            "Are there any significant changes to natural ecosystems in Indonesia this week?",
            DIST_ALERT,
        ),
        (
            "I need to monitor drought impacts on vegetation cover in East Africa",
            DIST_ALERT,
        ),
        (
            "What areas show signs of land management interventions in the past 6 months?",
            DIST_ALERT,
        ),
        # Dataset 1 queries (Global land cover) - annual land cover classification and change
        ("How much of the world is urban?", LAND_COVER_CHANGE),
        (
            "Which had more cropland in 2015, Nigeria or Ghana?",
            LAND_COVER_CHANGE,
        ),
        (
            "What's the trend in agricultural expansion across Southeast Asia since 2015?",
            LAND_COVER_CHANGE,
        ),
        (
            "I'm studying urbanization patterns in sub-Saharan Africa between 2020 and 2024",
            LAND_COVER_CHANGE,
        ),
        (
            "Show me areas where wetlands have been converted to other uses",
            LAND_COVER_CHANGE,
        ),
        # Dataset 2 queries (Grassland) - natural and cultivated grassland classification
        (
            "What is the total area of prairie ecosystems in North America?",
            GRASSLANDS,
        ),
        (
            "How much rangeland has been converted to agriculture in Mongolia since 2010?",
            GRASSLANDS,
        ),
        (
            "Which regions show the fastest decline in native grassland habitats?",
            GRASSLANDS,
        ),
        (
            "I need data on pastoral landscapes and their management intensity",
            GRASSLANDS,
        ),
        (
            "Where are the largest intact grassland ecosystems globally?",
            GRASSLANDS,
        ),
        # Dataset 3 queries (Natural lands) - SBTN baseline for conversion monitoring
        (
            "What percentage of land area in Brazil consists of natural ecosystems according to the 2020 baseline?",
            NATURAL_LANDS,
        ),
        (
            "Which provinces in Canada have the highest proportion of intact landscapes?",
            NATURAL_LANDS,
        ),
        (
            "Show me areas where natural habitats remain undisturbed by human activities",
            NATURAL_LANDS,
        ),
        (
            "What's the baseline extent of natural vegetation before any recent conversions?",
            NATURAL_LANDS,
        ),
        # Dataset 4 queries (Tree cover loss) - annual forest loss detection
        (
            "What percent of 2000 forest did Kalimantan Barat lose from 2001 through 2024?",
            TREE_COVER_LOSS,
        ),
        ("Which country had the most deforestation in 2018?", TREE_COVER_LOSS),
        (
            "I need to track plantation harvesting cycles in northern Europe",
            TREE_COVER_LOSS,
        ),
        (
            "What regions experienced the most fire-related forest damage last year?",
            TREE_COVER_LOSS,
        ),
        # Dataset 5 queries (Tree cover gain) - cumulative forest regrowth
        (
            "Where has forest regrowth occurred in the Amazon basin between 2000 and 2020?",
            TREE_COVER_GAIN,
        ),
        (
            "Show me areas of tree cover gain in Southeast Asia over the past two decades",
            TREE_COVER_GAIN,
        ),
        (
            "Which regions show the most significant forest recovery since 2000?",
            TREE_COVER_GAIN,
        ),
        # Dataset 6 queries (Forest greenhouse gas net flux) - carbon emissions and removals
        (
            "What areas of forest are acting as net carbon sinks versus sources?",
            CARBON_FLUX,
        ),
        (
            "Show me forest carbon emissions and removals in the Congo Basin",
            CARBON_FLUX,
        ),
        (
            "Which forest regions contribute most to greenhouse gas emissions?",
            CARBON_FLUX,
        ),
        # Dataset 7 queries (Tree cover) - baseline tree canopy density
        (
            "What percentage of land area in Brazil has tree cover above 30%?",
            TREE_COVER,
        ),
        (
            "Show me areas with high tree cover density in the Pacific Northwest",
            TREE_COVER,
        ),
        (
            "Which regions have the highest tree canopy cover globally?",
            TREE_COVER,
        ),
    ]
)
def test_query_with_expected_dataset(request):
    return request.param


@pytest.mark.asyncio
async def test_queries_return_expected_dataset(
    test_query_with_expected_dataset,
):
    query, expected_dataset = test_query_with_expected_dataset

    command = await pick_dataset.ainvoke(
        {
            "query": query,
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "tool_call_id": str(uuid.uuid4()),
        }
    )

    dataset_id = command.update.get("dataset", {}).get("dataset_id")
    assert dataset_id == lookup[expected_dataset]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query,expected_dataset_id,expected_context_layer",
    [
        ("Vegetation disturbances by natural lands", 0, "natural_lands"),
        ("Tree cover loss by driver", 4, "driver"),
        (
            "Dist alert problems split by natural land types",
            0,
            "natural_lands",
        ),
    ],
)
async def test_query_with_context_layer(
    query, expected_dataset_id, expected_context_layer
):
    command = await pick_dataset.ainvoke(
        {
            "query": query,
            "start_date": "2022-01-01",
            "end_date": "2022-12-31",
            "tool_call_id": str(uuid.uuid4()),
        }
    )

    dataset_id = command.update.get("dataset", {}).get("dataset_id")
    assert dataset_id == expected_dataset_id
    context_layer = command.update.get("dataset", {}).get("context_layer")
    assert context_layer == expected_context_layer


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "dataset",
    [
        DIST_ALERT,
        LAND_COVER_CHANGE,
        GRASSLANDS,
        NATURAL_LANDS,
        TREE_COVER,
        TREE_COVER_LOSS,
        TREE_COVER_GAIN,
        CARBON_FLUX,
    ],
)
async def test_tile_url_contains_date(dataset):
    year = "2020"
    if dataset == TREE_COVER:
        year = "2000"
    command = await pick_dataset.ainvoke(
        {
            "query": f"Find me {dataset} data for {year}",
            "start_date": f"{year}-01-01",
            "end_date": f"{year}-12-31",
            "tool_call_id": str(uuid.uuid4()),
        }
    )

    tile_url = command.update.get("dataset", {}).get("tile_url")
    if dataset not in [NATURAL_LANDS, TREE_COVER_GAIN, CARBON_FLUX]:
        assert year in tile_url
    response = requests.get(tile_url.format(z=3, x=5, y=3))
    assert response.status_code == 200
