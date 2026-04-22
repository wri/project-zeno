import pytest

from src.agent.tools.data_handlers.analytics_handler import (
    TREE_COVER_LOSS_ID,
    AnalyticsHandler,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture(scope="function", autouse=True)
def test_db():
    """Override the global test_db fixture to avoid database connections."""
    pass


@pytest.fixture(scope="function", autouse=True)
def test_db_session():
    """Override the global test_db_session fixture to avoid database connections."""
    pass


@pytest.fixture(scope="function", autouse=True)
def test_db_pool():
    """Override the global test_db_pool fixture to avoid database pool operations."""
    pass


async def test_build_payload_uses_canopy_cover_parameter():
    handler = AnalyticsHandler()
    dataset = {
        "dataset_id": TREE_COVER_LOSS_ID,
        "dataset_name": "Tree cover loss",
        "context_layer": None,
        "parameters": [{"name": "canopy_cover", "values": [50]}],
    }
    aois = [
        {
            "name": "Brazil",
            "subtype": "country",
            "src_id": "BRA",
        }
    ]

    payload = await handler._build_payload(
        dataset=dataset,
        aois=aois,
        start_date="2020-01-01",
        end_date="2024-12-31",
    )

    assert payload == {
        "aoi": {
            "type": "admin",
            "ids": ["BRA"],
        },
        "start_year": "2020",
        "end_year": "2024",
        "canopy_cover": 50,
        "forest_filter": None,
        "intersections": [],
    }


async def test_build_payload_uses_no_canopy_cover_parameter():
    handler = AnalyticsHandler()
    dataset = {
        "dataset_id": TREE_COVER_LOSS_ID,
        "dataset_name": "Tree cover loss",
        "context_layer": None,
    }
    aois = [
        {
            "name": "Brazil",
            "subtype": "country",
            "src_id": "BRA",
        }
    ]

    payload = await handler._build_payload(
        dataset=dataset,
        aois=aois,
        start_date="2020-01-01",
        end_date="2024-12-31",
    )

    assert payload == {
        "aoi": {
            "type": "admin",
            "ids": ["BRA"],
        },
        "start_year": "2020",
        "end_year": "2024",
        "canopy_cover": 30,
        "forest_filter": None,
        "intersections": [],
    }
