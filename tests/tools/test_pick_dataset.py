import uuid

import pytest

from src.tools.pick_dataset import pick_dataset


@pytest.fixture(scope="function", autouse=True)
def test_db():
    """Override the global test_db fixture to avoid database connections."""
    pass


@pytest.fixture(scope="function", autouse=True)
def test_db_session():
    """Override the global test_db_session fixture to avoid database connections."""
    pass


@pytest.fixture(
    params=[
        # Dataset 0 queries (Ecosystem disturbance alerts) - near-real-time vegetation changes
        (
            "Which year recorded more alerts within Protected Areas in Ucayali, Peru? 2023 or 2024?",
            0,
        ),
        (
            "Show me recent vegetation disturbances in the Amazon basin over the past month",
            0,
        ),
        (
            "Are there any significant changes to natural ecosystems in Indonesia this week?",
            0,
        ),
        (
            "I need to monitor drought impacts on vegetation cover in East Africa",
            0,
        ),
        (
            "What areas show signs of land management interventions in the past 6 months?",
            0,
        ),
        # Dataset 1 queries (Global land cover) - annual land cover classification and change
        ("How much of the world is urban?", 1),
        ("Which had more cropland in 2015, Nigeria or Ghana?", 1),
        (
            "What's the trend in agricultural expansion across Southeast Asia since 2015?",
            1,
        ),
        (
            "I'm studying urbanization patterns in sub-Saharan Africa between 2020 and 2024",
            1,
        ),
        ("Show me areas where wetlands have been converted to other uses", 1),
        # Dataset 2 queries (Grassland) - natural and cultivated grassland classification
        ("What is the total area of prairie ecosystems in North America?", 2),
        (
            "How much rangeland has been converted to agriculture in Mongolia since 2010?",
            2,
        ),
        (
            "Which regions show the fastest decline in native grassland habitats?",
            2,
        ),
        (
            "I need data on pastoral landscapes and their management intensity",
            2,
        ),
        ("Where are the largest intact grassland ecosystems globally?", 2),
        # Dataset 3 queries (Natural lands) - SBTN baseline for conversion monitoring
        (
            "What percentage of land area in Brazil consists of natural ecosystems according to the 2020 baseline?",
            3,
        ),
        (
            "I'm monitoring my supply chain for conversion of natural ecosystems",
            3,
        ),
        (
            "Which provinces in Canada have the highest proportion of intact landscapes?",
            3,
        ),
        (
            "Show me areas where natural habitats remain undisturbed by human activities",
            3,
        ),
        (
            "What's the baseline extent of natural vegetation before any recent conversions?",
            3,
        ),
        # Dataset 4 queries (Tree cover loss) - annual forest loss detection
        (
            "What percent of 2000 forest did Kalimantan Barat lose from 2001 through 2024?",
            4,
        ),
        ("Which country had the most deforestation in 2018?", 4),
        ("Show me areas of recent forest clearing in the Congo Basin", 4),
        ("I need to track plantation harvesting cycles in northern Europe", 4),
        (
            "What regions experienced the most fire-related forest damage last year?",
            4,
        ),
    ]
)
def test_query_with_expected_dataset(request):
    return request.param


def test_queries_return_expected_dataset(test_query_with_expected_dataset):
    query, expected_dataset_id = test_query_with_expected_dataset

    command = pick_dataset.invoke(
        {
            "query": query,
            "tool_call_id": str(uuid.uuid4()),
        }
    )

    dataset_id = command.update.get("dataset", {}).get("dataset_id")
    assert dataset_id == expected_dataset_id
