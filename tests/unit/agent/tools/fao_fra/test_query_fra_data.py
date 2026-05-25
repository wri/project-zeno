"""Unit tests for the `query_fra_data` primitive tool.

No network. `fetch_fra_data` is monkeypatched so we exercise: state reading
(country filter + redirect), unknown-variable redirect, multi-country
aggregation, partial-failure aggregation, and the dataset-injection contract
that lets `generate_insights` pick up FAO `presentation_instructions`.
"""

from unittest.mock import AsyncMock

from src.agent.tools.query_fra_data import query_fra_data


def _make_state(*aois: dict) -> dict:
    return {"aoi_selection": {"name": "test", "aois": list(aois)}}


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


async def _invoke(args: dict) -> dict:
    """Helper: invoke the @tool wrapper and return the Command.update dict."""
    cmd = await query_fra_data.ainvoke(
        {
            "type": "tool_call",
            "name": "query_fra_data",
            "id": args.get("tool_call_id", "tc"),
            "args": {"tool_call_id": "tc", **args},
        }
    )
    return cmd.update


# ---------------------------------------------------------------------------
# Variable validation
# ---------------------------------------------------------------------------


async def test_unknown_variable_returns_human_feedback(monkeypatch):
    update = await _invoke(
        {
            "variable": "not_a_real_variable",
            "state": _make_state(_country("Brazil", "BRA")),
        }
    )
    msg = update["messages"][0]
    assert msg.response_metadata["msg_type"] == "human_feedback"
    assert "not a recognised FAO FRA variable" in msg.content
    # No statistics or dataset on the redirect path
    assert "statistics" not in update
    assert "dataset" not in update


# ---------------------------------------------------------------------------
# AOI gating — country-level only
# ---------------------------------------------------------------------------


async def test_no_aoi_returns_redirect(monkeypatch):
    update = await _invoke({"variable": "forest_area", "state": _make_state()})
    msg = update["messages"][0]
    assert "country-level" in msg.content
    assert "statistics" not in update


async def test_sub_national_aoi_returns_redirect(monkeypatch):
    state_aoi = {
        "name": "Amazonas",
        "src_id": "BRA.4_1",
        "source": "gadm",
        "subtype": "state",
    }
    update = await _invoke(
        {"variable": "forest_area", "state": _make_state(state_aoi)}
    )
    msg = update["messages"][0]
    assert "country-level" in msg.content
    assert "statistics" not in update


async def test_non_gadm_aoi_returns_redirect(monkeypatch):
    kba_aoi = {
        "name": "Yellowstone KBA",
        "src_id": "12345",
        "source": "kba",
        "subtype": "kba",
    }
    update = await _invoke(
        {"variable": "forest_area", "state": _make_state(kba_aoi)}
    )
    assert "country-level" in update["messages"][0].content


# ---------------------------------------------------------------------------
# Happy path — single country
# ---------------------------------------------------------------------------


async def test_single_country_fetches_and_writes_statistics(monkeypatch):
    fake_fetch = AsyncMock(return_value=_records_for("BRA"))
    monkeypatch.setattr(
        "src.agent.datasets.handlers.fao_fra_client.fetch_fra_data", fake_fetch
    )

    update = await _invoke(
        {
            "variable": "forest_area",
            "state": _make_state(_country("Brazil", "BRA")),
        }
    )

    fake_fetch.assert_awaited_once()
    call = fake_fetch.await_args.kwargs
    assert call["iso3"] == "BRA"
    assert call["table"] == "extentOfForest"
    assert call["year"] is None

    stats = update["statistics"]
    assert len(stats) == 1
    entry = stats[0]
    assert entry["aoi_names"] == ["Brazil"]
    assert entry["context_layer"] is None
    assert entry["parameters"] is None
    # Data is inline (FAO responses are small)
    assert entry["data"]
    # Records carry the human-readable aoi_name added by the tool
    assert all(r.get("aoi_name") == "Brazil" for r in entry["data"])

    # dataset is injected so generate_insights picks up FAO instructions
    assert update["dataset"]["dataset_id"] == 10


async def test_year_arg_propagates_to_client(monkeypatch):
    fake_fetch = AsyncMock(return_value=_records_for("BRA"))
    monkeypatch.setattr(
        "src.agent.datasets.handlers.fao_fra_client.fetch_fra_data", fake_fetch
    )

    await _invoke(
        {
            "variable": "forest_area",
            "year": 2020,
            "state": _make_state(_country("Brazil", "BRA")),
        }
    )
    assert fake_fetch.await_args.kwargs["year"] == 2020


# ---------------------------------------------------------------------------
# Multi-country aggregation
# ---------------------------------------------------------------------------


async def test_multi_country_concatenates_records(monkeypatch):
    side_effects = {"BRA": _records_for("BRA"), "IDN": _records_for("IDN")}

    async def fake_fetch(iso3, table, variables, year=None):
        return side_effects[iso3]

    monkeypatch.setattr(
        "src.agent.datasets.handlers.fao_fra_client.fetch_fra_data", fake_fetch
    )

    update = await _invoke(
        {
            "variable": "forest_area",
            "state": _make_state(
                _country("Brazil", "BRA"),
                _country("Indonesia", "IDN"),
            ),
        }
    )

    entry = update["statistics"][0]
    assert entry["aoi_names"] == ["Brazil", "Indonesia"]
    aoi_names_in_data = {r["aoi_name"] for r in entry["data"]}
    assert aoi_names_in_data == {"Brazil", "Indonesia"}


# ---------------------------------------------------------------------------
# Partial failure — one country missing data, others succeed
# ---------------------------------------------------------------------------


async def test_partial_failure_yields_data_plus_note(monkeypatch):
    from src.agent.datasets.handlers.fao_fra_client import (
        FAODataNotFoundError,
    )

    async def fake_fetch(iso3, table, variables, year=None):
        if iso3 == "XXX":
            raise FAODataNotFoundError("no data for XXX")
        return _records_for(iso3)

    monkeypatch.setattr(
        "src.agent.datasets.handlers.fao_fra_client.fetch_fra_data", fake_fetch
    )

    update = await _invoke(
        {
            "variable": "forest_area",
            "state": _make_state(
                _country("Brazil", "BRA"),
                _country("Nowhereland", "XXX"),
            ),
        }
    )

    # Statistics populated from the successful country
    entry = update["statistics"][0]
    assoc_names = {r["aoi_name"] for r in entry["data"]}
    assert assoc_names == {"Brazil"}
    # The failing country surfaced in the tool message
    msg = update["messages"][0].content
    assert "no data for XXX" in msg


async def test_total_failure_returns_human_feedback(monkeypatch):
    from src.agent.datasets.handlers.fao_fra_client import FAOAPIError

    async def fake_fetch(iso3, table, variables, year=None):
        raise FAOAPIError("FAO API is down")

    monkeypatch.setattr(
        "src.agent.datasets.handlers.fao_fra_client.fetch_fra_data", fake_fetch
    )

    update = await _invoke(
        {
            "variable": "forest_area",
            "state": _make_state(_country("Brazil", "BRA")),
        }
    )
    msg = update["messages"][0]
    assert msg.response_metadata["msg_type"] == "human_feedback"
    assert "FAO API is down" in msg.content
    assert "statistics" not in update


# ---------------------------------------------------------------------------
# Dataset injection contract
# ---------------------------------------------------------------------------


async def test_dataset_is_injected_for_generate_insights(monkeypatch):
    fake_fetch = AsyncMock(return_value=_records_for("BRA"))
    monkeypatch.setattr(
        "src.agent.datasets.handlers.fao_fra_client.fetch_fra_data", fake_fetch
    )

    update = await _invoke(
        {
            "variable": "carbon_stock",
            "state": _make_state(_country("Brazil", "BRA")),
        }
    )
    dataset = update["dataset"]
    # generate_insights reads these three keys from state["dataset"]
    assert dataset["code_instructions"]
    assert dataset["presentation_instructions"]
    assert dataset["cautions"]
