"""Unit tests for FAOFRAHandler.

`fetch_fra_data` is monkeypatched so we exercise: dispatch via `can_handle`,
context_layer resolution from the dataset YAML, country-AOI gating,
multi-country aggregation, partial-failure aggregation, and the DataPullResult
shape that `pull_data` consumes.
"""

from unittest.mock import AsyncMock

from src.agent.datasets.config import DATASETS
from src.agent.datasets.handlers import fao_fra_handler as handler_mod
from src.agent.datasets.handlers.fao_fra_client import (
    FAOAPIError,
    FAODataNotFoundError,
)
from src.agent.datasets.handlers.fao_fra_handler import (
    FAO_FRA_2025_DATASET_ID,
    FAOFRAHandler,
)


def _fao_dataset(context_layer_value: str | None = "forest_area") -> dict:
    """Return the catalog FAO dataset dict with the chosen context_layer
    set the way `pick_dataset` would set it."""
    fao = next(
        d for d in DATASETS if d["dataset_id"] == FAO_FRA_2025_DATASET_ID
    )
    # pick_dataset writes the LLM-picked value into `context_layer` on the
    # state dict (alongside the catalog's `context_layers` list).
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
    h = FAOFRAHandler()
    assert h.can_handle({"dataset_id": FAO_FRA_2025_DATASET_ID})
    assert not h.can_handle({"dataset_id": 4})  # tree_cover_loss
    assert not h.can_handle({})


# ---------------------------------------------------------------------------
# context_layer resolution
# ---------------------------------------------------------------------------


async def test_no_context_layer_returns_failure_with_actionable_message():
    h = FAOFRAHandler()
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
    h = FAOFRAHandler()
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
    h = FAOFRAHandler()
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
    h = FAOFRAHandler()
    state_aoi = {
        "name": "Amazonas",
        "src_id": "BRA.4_1",
        "source": "gadm",
        "subtype": "state",
    }
    result = await h.pull_data(
        query="forest area",
        dataset=_fao_dataset("forest_area"),
        start_date="1990-01-01",
        end_date="2025-12-31",
        change_over_time_query=False,
        aois=[state_aoi],
    )
    assert not result.success
    assert "country-level" in result.message


async def test_kba_aoi_filtered_out():
    h = FAOFRAHandler()
    kba_aoi = {
        "name": "Some KBA",
        "src_id": "12345",
        "source": "kba",
        "subtype": "key-biodiversity-area",
    }
    result = await h.pull_data(
        query="forest area",
        dataset=_fao_dataset("forest_area"),
        start_date="1990-01-01",
        end_date="2025-12-31",
        change_over_time_query=False,
        aois=[kba_aoi],
    )
    assert not result.success


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


async def test_single_country_returns_inline_records(monkeypatch):
    fake = AsyncMock(return_value=_records_for("BRA"))
    monkeypatch.setattr(handler_mod, "fetch_fra_data", fake)

    h = FAOFRAHandler()
    result = await h.pull_data(
        query="forest area",
        dataset=_fao_dataset("forest_area"),
        start_date="1990-01-01",
        end_date="2025-12-31",
        change_over_time_query=False,
        aois=[_country("Brazil", "BRA")],
    )

    fake.assert_awaited_once()
    call = fake.await_args.kwargs
    assert call["iso3"] == "BRA"
    assert call["table"] == "extentOfForest"  # from the YAML
    assert call["variables"] == [
        "forestArea",
        "naturallyRegeneratingForest",
        "plantedForest",
        "primaryForest",
    ]

    assert result.success
    assert isinstance(result.data, dict)
    records = result.data["data"]
    assert len(records) == 2
    # Handler tags each record with the human-readable AOI name
    assert all(r.get("aoi_name") == "Brazil" for r in records)
    assert result.data_points_count == 2
    assert result.analytics_api_url
    assert "BRA" in result.analytics_api_url


async def test_multi_country_aggregates_records(monkeypatch):
    async def fake_fetch(*, iso3, table, variables, year=None):
        return _records_for(iso3)

    monkeypatch.setattr(handler_mod, "fetch_fra_data", fake_fetch)

    h = FAOFRAHandler()
    result = await h.pull_data(
        query="forest area",
        dataset=_fao_dataset("forest_area"),
        start_date="1990-01-01",
        end_date="2025-12-31",
        change_over_time_query=False,
        aois=[_country("Brazil", "BRA"), _country("Indonesia", "IDN")],
    )

    assert result.success
    records = result.data["data"]
    aoi_names_seen = {r["aoi_name"] for r in records}
    assert aoi_names_seen == {"Brazil", "Indonesia"}


async def test_uses_fao_table_from_selected_layer(monkeypatch):
    """When pick_dataset picks a different context_layer, the handler
    routes to the matching fao_table."""
    captured = {}

    async def fake_fetch(*, iso3, table, variables, year=None):
        captured["table"] = table
        captured["variables"] = variables
        return _records_for(iso3)

    monkeypatch.setattr(handler_mod, "fetch_fra_data", fake_fetch)

    h = FAOFRAHandler()
    await h.pull_data(
        query="carbon",
        dataset=_fao_dataset("carbon_stock"),
        start_date="1990-01-01",
        end_date="2025-12-31",
        change_over_time_query=False,
        aois=[_country("Brazil", "BRA")],
    )
    assert captured["table"] == "carbonStockTotal"
    assert captured["variables"] == ["total"]


# ---------------------------------------------------------------------------
# Partial / total failure
# ---------------------------------------------------------------------------


async def test_partial_failure_yields_records_plus_note(monkeypatch):
    async def fake_fetch(*, iso3, table, variables, year=None):
        if iso3 == "XXX":
            raise FAODataNotFoundError("no data for XXX")
        return _records_for(iso3)

    monkeypatch.setattr(handler_mod, "fetch_fra_data", fake_fetch)

    h = FAOFRAHandler()
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
    assert "Nowhereland" in result.message  # error note surfaces


async def test_total_failure_returns_failure_result(monkeypatch):
    async def fake_fetch(*, iso3, table, variables, year=None):
        raise FAOAPIError("FAO API is down")

    monkeypatch.setattr(handler_mod, "fetch_fra_data", fake_fetch)

    h = FAOFRAHandler()
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
