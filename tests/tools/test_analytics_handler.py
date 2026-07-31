import pytest

from src.agent.datasets.handlers.analytics_handler import (
    TREE_COVER_LOSS_ID,
    AnalyticsHandler,
    _count_and_enrich,
    _merge_lgms_sections,
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


# --- LGMS per-section result merged into one flat category/class table -------
# The Land GHG Monitoring System returns a per-section result; the handler
# flattens it into one column-oriented table with unified category/class
# dimensions (metrics absent from a section filled with None).


async def test_merge_lgms_sections_flattens_to_category_class_table():
    raw = {
        "vegetation": {
            "aoi_id": ["BRA.25", "BRA.25"],
            "aoi_type": ["admin", "admin"],
            "land_state_class": ["tree_loss", "tree_gain"],
            "year": [2016, 2016],
            "gross_emissions_MgCO2e": [10.0, 0.0],
            "gross_removals_MgCO2": [-1.0, -2.0],
            "net_flux_MgCO2e": [9.0, -2.0],
            "area_ha": [100.0, 50.0],
        },
        "mineral_soil": {
            "aoi_id": ["BRA.25"],
            "aoi_type": ["admin"],
            "year": [2016],
            "gross_emissions_MgCO2e": [5.0],
            "gross_removals_MgCO2": [-1.0],
            "net_flux_MgCO2e": [4.0],
            "area_ha": [200.0],
        },
        "organic_soil": {
            "aoi_id": ["BRA.25"],
            "aoi_type": ["admin"],
            "year": [2016],
            "gross_emissions_MgCO2e": [3.0],
            "area_ha": [7.0],
        },
        "agriculture": {
            "aoi_id": ["BRA.25"],
            "aoi_type": ["admin"],
            "category": ["cropland"],
            "gross_emissions_MgCO2e": [33.0],
        },
    }
    merged = _merge_lgms_sections(raw)
    assert len(merged["category"]) == 5  # 2 + 1 + 1 + 1 rows
    assert merged["category"] == [
        "vegetation",
        "vegetation",
        "soil",
        "soil",
        "agriculture",
    ]
    assert merged["class"] == [
        "tree_loss",
        "tree_gain",
        "mineral",
        "organic",
        "cropland",
    ]
    # Agriculture is labelled 2020 (its reporting year); other absent metrics
    # are None (agriculture: removals/net flux/area; organic soil:
    # removals/net flux).
    assert merged["year"] == [2016, 2016, 2016, 2016, 2020]
    assert merged["gross_removals_MgCO2"] == [-1.0, -2.0, -1.0, None, None]
    assert merged["net_flux_MgCO2e"] == [9.0, -2.0, 4.0, None, None]
    assert merged["area_ha"] == [100.0, 50.0, 200.0, 7.0, None]
    # The flat merged table then counts + name-enriches normally.
    _, count = _count_and_enrich(
        merged, [{"src_id": "BRA.25", "name": "São Paulo, Brazil"}]
    )
    assert count == 5


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
