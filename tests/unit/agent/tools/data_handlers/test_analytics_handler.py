from src.agent.tools.data_handlers.analytics_handler import (
    TREE_COVER_LOSS_BY_DRIVER_ID,
    TREE_COVER_LOSS_ID,
    AnalyticsHandler,
)


def test_build_payload_tree_cover_loss_primary_forest_admin_aoi():
    handler = AnalyticsHandler()
    dataset = {
        "dataset_id": TREE_COVER_LOSS_ID,
        "context_layer": "primary_forest",
    }
    aoi = {
        "type": "admin",
        "ids": ["BRA.14"],
    }

    payload = handler._build_payload(
        dataset=dataset,
        aois=aoi,
        start_date="2024-01-01",
        end_date="2024-12-31",
    )

    assert payload == {
        "aoi": {
            "type": "admin",
            "ids": ["BRA.14"],
        },
        "start_year": "2024",
        "end_year": "2024",
        "canopy_cover": 30,
        "forest_filter": "primary_forest",
        "intersections": [],
    }


def test_build_payload_tree_cover_loss_driver_admin_aoi():
    handler = AnalyticsHandler()
    dataset = {
        "dataset_id": TREE_COVER_LOSS_BY_DRIVER_ID,
        "context_layer": None,
    }
    aoi = {
        "type": "admin",
        "ids": ["BRA.14"],
    }

    payload = handler._build_payload(
        dataset=dataset,
        aois=aoi,
        start_date="2024-01-01",
        end_date="2024-12-31",
    )

    assert payload == {
        "aoi": {
            "type": "admin",
            "ids": ["BRA.14"],
        },
        "start_year": "2024",
        "end_year": "2024",
        "canopy_cover": 30,
        "forest_filter": None,
        "intersections": ["drivers"],
    }
