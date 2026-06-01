"""Unit tests for FAOFRAHandler.

A mock FAOFRAClient is injected at construction so tests exercise: dispatch
via `can_handle`, context_layer resolution from the dataset YAML,
country-AOI gating, multi-country aggregation, partial-failure aggregation,
and the DataPullResult shape that `pull_data` consumes — with no network
calls and no monkey-patching of module-level names.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent.datasets.config import DATASETS
from src.agent.datasets.handlers.fao_fra_client import (
    FAOAPIError,
    FAODataNotFoundError,
    FAOFRAClient,
)
from src.agent.datasets.handlers.fao_fra_handler import (
    FAO_FRA_2025_DATASET_ID,
    FAOFRAHandler,
)


def _mock_client(records=None, side_effect=None) -> FAOFRAClient:
    """Return a mock FAOFRAClient with fetch pre-configured."""
    client = AsyncMock(spec=FAOFRAClient)
    client.build_source_url = MagicMock(
        return_value="https://fra-data.fao.org/api/explorer/data"
        "?assessmentName=fra&countryISOs[]=BRA&tableNames[]=extentOfForest"
    )
    if side_effect is not None:
        client.fetch.side_effect = side_effect
    else:
        client.fetch.return_value = records or []
    return client


def _fao_dataset(context_layer_value: str | None = "forest_area") -> dict:
    """Return the catalog FAO dataset dict with the chosen context_layer
    set the way `pick_dataset` would set it."""
    fao = next(
        d for d in DATASETS if d["dataset_id"] == FAO_FRA_2025_DATASET_ID
    )
    return {**fao, "context_layer": context_layer_value}


def _country(name: str, iso3: str) -> dict:
    return {
        "name": name,
        "src_id": iso3,
        "source": "gadm",
        "subtype": "country",
    }


def _records_for(iso3: str) -> list[dict]:
    return [
        {
            "year": 1990,
            "variable": "forestArea",
            "value": 100.0,
            "odp": True,
            "country": iso3,
        },
        {
            "year": 2025,
            "variable": "forestArea",
            "value": 95.0,
            "odp": True,
            "country": iso3,
        },
    ]


# ---------------------------------------------------------------------------
# can_handle
# ---------------------------------------------------------------------------


def test_can_handle_matches_fao_dataset_id():
    h = FAOFRAHandler(client=_mock_client())
    assert h.can_handle({"dataset_id": FAO_FRA_2025_DATASET_ID})
    assert not h.can_handle({"dataset_id": 4})  # tree_cover_loss
    assert not h.can_handle({})


# ---------------------------------------------------------------------------
# context_layer resolution
# ---------------------------------------------------------------------------


async def test_no_context_layer_returns_failure_with_actionable_message():
    h = FAOFRAHandler(client=_mock_client())
    result = await h.pull_data(
        query="forests",
        dataset=_fao_dataset(context_layer_value=None),
        start_date="1990-01-01",
        end_date="2025-12-31",
        change_over_time_query=False,
        aois=[_country("Brazil", "BRA")],
    )
    assert not result.success
    assert "context_layer" in result.message
    assert result.data == {"data": []}


async def test_unknown_context_layer_returns_failure():
    h = FAOFRAHandler(client=_mock_client())
    result = await h.pull_data(
        query="anything",
        dataset=_fao_dataset(context_layer_value="not_a_real_variable"),
        start_date="1990-01-01",
        end_date="2025-12-31",
        change_over_time_query=False,
        aois=[_country("Brazil", "BRA")],
    )
    assert not result.success
    assert "context_layer" in result.message


# ---------------------------------------------------------------------------
# AOI gating
# ---------------------------------------------------------------------------


async def test_no_country_aois_returns_redirect():
    h = FAOFRAHandler(client=_mock_client())
    result = await h.pull_data(
        query="forest area",
        dataset=_fao_dataset("forest_area"),
        start_date="1990-01-01",
        end_date="2025-12-31",
        change_over_time_query=False,
        aois=[],
    )
    assert not result.success
    assert "country-level" in result.message


async def test_sub_national_aoi_filtered_out():
    h = FAOFRAHandler(client=_mock_client())
    result = await h.pull_data(
        query="forest area",
        dataset=_fao_dataset("forest_area"),
        start_date="1990-01-01",
        end_date="2025-12-31",
        change_over_time_query=False,
        aois=[
            {
                "name": "Amazonas",
                "src_id": "BRA.4_1",
                "source": "gadm",
                "subtype": "state",
            }
        ],
    )
    assert not result.success
    assert "country-level" in result.message


async def test_kba_aoi_filtered_out():
    h = FAOFRAHandler(client=_mock_client())
    result = await h.pull_data(
        query="forest area",
        dataset=_fao_dataset("forest_area"),
        start_date="1990-01-01",
        end_date="2025-12-31",
        change_over_time_query=False,
        aois=[
            {
                "name": "Some KBA",
                "src_id": "12345",
                "source": "kba",
                "subtype": "key-biodiversity-area",
            }
        ],
    )
    assert not result.success


# ---------------------------------------------------------------------------
# Happy paths — interface and result shape tested separately (comment 16)
# ---------------------------------------------------------------------------


async def test_single_country_calls_client_with_correct_args():
    client = _mock_client(records=_records_for("BRA"))
    h = FAOFRAHandler(client=client)
    await h.pull_data(
        query="forest area",
        dataset=_fao_dataset("forest_area"),
        start_date="1990-01-01",
        end_date="2025-12-31",
        change_over_time_query=False,
        aois=[_country("Brazil", "BRA")],
    )
    client.fetch.assert_awaited_once_with(
        iso3="BRA",
        table="extentOfForest",
        variables=[
            "forestArea",
            "naturallyRegeneratingForest",
            "plantedForest",
            "primaryForest",
        ],
    )


async def test_single_country_result_shape():
    client = _mock_client(records=_records_for("BRA"))
    h = FAOFRAHandler(client=client)
    result = await h.pull_data(
        query="forest area",
        dataset=_fao_dataset("forest_area"),
        start_date="1990-01-01",
        end_date="2025-12-31",
        change_over_time_query=False,
        aois=[_country("Brazil", "BRA")],
    )
    assert result.success
    records = result.data["data"]
    assert len(records) == 2
    assert all(r.get("aoi_name") == "Brazil" for r in records)
    assert result.data_points_count == 2
    assert result.analytics_api_url is not None


async def test_multi_country_aggregates_records():
    async def by_country(*, iso3, table, variables, year=None):
        return _records_for(iso3)

    client = _mock_client(side_effect=by_country)
    h = FAOFRAHandler(client=client)
    result = await h.pull_data(
        query="forest area",
        dataset=_fao_dataset("forest_area"),
        start_date="1990-01-01",
        end_date="2025-12-31",
        change_over_time_query=False,
        aois=[_country("Brazil", "BRA"), _country("Indonesia", "IDN")],
    )
    assert result.success
    aoi_names_seen = {r["aoi_name"] for r in result.data["data"]}
    assert aoi_names_seen == {"Brazil", "Indonesia"}


async def test_uses_fao_table_from_selected_layer():
    """When pick_dataset picks a different context_layer the handler routes
    to the matching fao_table from the YAML."""
    client = _mock_client(records=_records_for("BRA"))
    h = FAOFRAHandler(client=client)
    await h.pull_data(
        query="carbon",
        dataset=_fao_dataset("carbon_stock"),
        start_date="1990-01-01",
        end_date="2025-12-31",
        change_over_time_query=False,
        aois=[_country("Brazil", "BRA")],
    )
    client.fetch.assert_awaited_once_with(
        iso3="BRA",
        table="carbonStockTotal",
        variables=["total"],
    )


# ---------------------------------------------------------------------------
# Partial / total failure
# ---------------------------------------------------------------------------


async def test_partial_failure_yields_records_plus_note():
    async def side_effect(*, iso3, table, variables, year=None):
        if iso3 == "XXX":
            raise FAODataNotFoundError("no data for XXX")
        return _records_for(iso3)

    client = _mock_client(side_effect=side_effect)
    h = FAOFRAHandler(client=client)
    result = await h.pull_data(
        query="forest area",
        dataset=_fao_dataset("forest_area"),
        start_date="1990-01-01",
        end_date="2025-12-31",
        change_over_time_query=False,
        aois=[
            _country("Brazil", "BRA"),
            _country("Nowhereland", "XXX"),
        ],
    )
    assert result.success
    aoi_names_seen = {r["aoi_name"] for r in result.data["data"]}
    assert aoi_names_seen == {"Brazil"}
    assert "Nowhereland" in result.message


async def test_total_failure_returns_failure_result():
    client = _mock_client(side_effect=FAOAPIError("FAO API is down"))
    h = FAOFRAHandler(client=client)
    result = await h.pull_data(
        query="forest area",
        dataset=_fao_dataset("forest_area"),
        start_date="1990-01-01",
        end_date="2025-12-31",
        change_over_time_query=False,
        aois=[_country("Brazil", "BRA")],
    )
    assert not result.success
    assert "FAO API is down" in result.message
