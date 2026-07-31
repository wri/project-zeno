import pytest

from src.agent.datasets.handlers.analytics_handler import (
    TREE_COVER_LOSS_ID,
    AnalyticsHandler,
    _count_and_enrich,
    format_id,
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


# --- Nested (per-section) analytics results, e.g. Land GHG Monitoring System (LGMS) ----------
# A nested result must NOT go through the flat aoi_id name-enrichment path, and
# the data-point count comes from the first inner section's first list.


async def test_nested_result_counts_and_skips_name_enrichment():
    raw = {
        "vegetation": {
            "year": [2016, 2017, 2018],
            "net_flux_MgCO2e": [1, 2, 3],
        },
        "agriculture": {
            "category": ["cropland"],
            "gross_emissions_MgCO2e": [9],
        },
    }
    enriched, count = _count_and_enrich(
        raw, [{"src_id": "BRA.25", "name": "São Paulo, Brazil"}]
    )
    assert count == 3  # first section's first list length
    assert "name" not in enriched  # nested results skip aoi_id enrichment


async def test_flat_result_enriches_names_and_counts():
    aois = [
        {"src_id": "BRA", "name": "Brazil"},
        {"src_id": "ARG", "name": "Argentina"},
    ]
    raw = {
        "aoi_id": [format_id("BRA"), format_id("ARG")],
        "value": [10, 20],
    }
    enriched, count = _count_and_enrich(raw, aois)
    assert count == 2
    assert enriched["name"] == ["Brazil", "Argentina"]
