"""Tests for query_fra_data tool and fao_client module."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent.tools.fao_client import (
    FAOAPIError,
    FAODataNotFoundError,
    _parse_response,
    fetch_fra_data,
)
from src.agent.tools.query_fra_data import query_fra_data
from src.agent.tools.variable_map import VALID_VARIABLES

pytestmark = pytest.mark.asyncio(loop_scope="session")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function", autouse=True)
def test_db():
    """Override the global test_db fixture to avoid database connections."""
    pass


@pytest.fixture(scope="function", autouse=True)
def test_db_session():
    pass


@pytest.fixture(scope="function", autouse=True)
def test_db_pool():
    pass


def _make_state(iso3: str = "BRA", aoi_name: str = "Brazil") -> dict:
    return {
        "aoi_selection": {
            "name": aoi_name,
            "aois": [
                {
                    "name": aoi_name,
                    "src_id": iso3,
                    "source": "gadm",
                    "subtype": "country",
                }
            ],
        }
    }


def _make_fao_response(iso3: str, table: str) -> dict:
    """Build a minimal but realistic FAO API response body."""
    return {
        "fra": {
            "2025": {
                iso3: {
                    table: {
                        "1990": {
                            "forestArea": {"raw": "493538.00", "odp": True, "faoEstimate": False},
                        },
                        "2000": {
                            "forestArea": {"raw": "483418.00", "odp": True, "faoEstimate": False},
                        },
                        "2025": {
                            "forestArea": {"raw": "462700.00", "odp": True, "faoEstimate": False},
                        },
                    }
                }
            }
        }
    }


def _tool_call(variable: str, year: int | None = None, state: dict | None = None) -> dict:
    args = {
        "query": "What is the total forest area?",
        "variable": variable,
        "tool_call_id": str(uuid.uuid4()),
        "state": state or _make_state(),
    }
    if year is not None:
        args["year"] = year
    return {
        "type": "tool_call",
        "name": "query_fra_data",
        "id": args["tool_call_id"],
        "args": args,
    }


# ---------------------------------------------------------------------------
# _parse_response unit tests
# ---------------------------------------------------------------------------

class TestParseResponse:
    def test_happy_path_returns_records(self):
        body = _make_fao_response("BRA", "extentOfForest")
        records = _parse_response(body, "BRA", "extentOfForest", year=None)
        assert len(records) == 3
        years = {r["year"] for r in records}
        assert years == {1990, 2000, 2025}
        assert all(r["variable"] == "forestArea" for r in records)
        assert all(r["country"] == "BRA" for r in records)

    def test_year_filter(self):
        body = _make_fao_response("BRA", "extentOfForest")
        records = _parse_response(body, "BRA", "extentOfForest", year=2000)
        assert len(records) == 1
        assert records[0]["year"] == 2000
        assert records[0]["value"] == pytest.approx(483418.0)

    def test_missing_country_raises(self):
        body = {"fra": {"2025": {"FIN": {}}}}
        with pytest.raises(FAODataNotFoundError, match="BRA"):
            _parse_response(body, "BRA", "extentOfForest", year=None)

    def test_missing_table_raises(self):
        body = {"fra": {"2025": {"BRA": {"otherTable": {}}}}}
        with pytest.raises(FAODataNotFoundError, match="extentOfForest"):
            _parse_response(body, "BRA", "extentOfForest", year=None)

    def test_null_raw_value_becomes_none(self):
        body = {
            "fra": {
                "2025": {
                    "BRA": {
                        "extentOfForest": {
                            "2025": {"forestArea": {"raw": None, "odp": False}}
                        }
                    }
                }
            }
        }
        records = _parse_response(body, "BRA", "extentOfForest", year=None)
        assert records[0]["value"] is None

    def test_empty_body_raises(self):
        with pytest.raises(FAODataNotFoundError):
            _parse_response({}, "BRA", "extentOfForest", year=None)


# ---------------------------------------------------------------------------
# fetch_fra_data unit tests (mock httpx)
# ---------------------------------------------------------------------------

class TestFetchFraData:
    async def test_success_returns_records(self):
        body = _make_fao_response("BRA", "extentOfForest")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = body

        with patch("src.agent.tools.fao_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            records = await fetch_fra_data("BRA", "extentOfForest", ["forestArea"])

        assert len(records) == 3
        assert records[0]["country"] == "BRA"

    async def test_timeout_raises_api_error(self):
        import httpx as _httpx

        with patch("src.agent.tools.fao_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=_httpx.TimeoutException("timeout"))
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(FAOAPIError, match="did not respond"):
                await fetch_fra_data("BRA", "extentOfForest", [])

    async def test_500_raises_api_error(self):
        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch("src.agent.tools.fao_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(FAOAPIError, match="server error"):
                await fetch_fra_data("BRA", "extentOfForest", [])

    async def test_404_raises_not_found_error(self):
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("src.agent.tools.fao_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(FAODataNotFoundError):
                await fetch_fra_data("XYZ", "extentOfForest", [])


# ---------------------------------------------------------------------------
# query_fra_data tool integration tests
# ---------------------------------------------------------------------------

class TestQueryFraDataTool:
    async def test_happy_path_updates_statistics(self):
        body = _make_fao_response("BRA", "extentOfForest")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = body

        with patch("src.agent.tools.fao_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            command = await query_fra_data.ainvoke(_tool_call("forest_area"))

        stats = command.update.get("statistics", [])
        assert len(stats) == 1
        assert stats[0]["dataset_name"] == "FAO FRA 2025"
        assert stats[0]["aoi_names"] == ["Brazil"]
        data = stats[0]["data"]
        assert data["variable"] == "forest_area"
        assert len(data["data"]) == 3  # 1990, 2000, 2025
        # Records should carry aoi_name
        assert all(r["aoi_name"] == "Brazil" for r in data["data"])

    async def test_invalid_variable_returns_error_tool_message(self):
        command = await query_fra_data.ainvoke(_tool_call("nonexistent_variable"))

        assert "statistics" not in command.update
        messages = command.update.get("messages", [])
        assert len(messages) == 1
        content = messages[0].content
        assert "nonexistent_variable" in content
        assert "Valid options" in content

    async def test_fao_api_error_returns_error_tool_message(self):
        with patch(
            "src.agent.tools.query_fra_data.fetch_fra_data",
            new=AsyncMock(side_effect=FAOAPIError("API down")),
        ):
            command = await query_fra_data.ainvoke(_tool_call("forest_area"))

        assert "statistics" not in command.update
        messages = command.update.get("messages", [])
        assert messages[0].content == "API down"

    async def test_data_not_found_returns_error_tool_message(self):
        with patch(
            "src.agent.tools.query_fra_data.fetch_fra_data",
            new=AsyncMock(side_effect=FAODataNotFoundError("Country not in FRA")),
        ):
            command = await query_fra_data.ainvoke(_tool_call("forest_area"))

        assert "statistics" not in command.update
        assert "Country not in FRA" in command.update["messages"][0].content

    async def test_iso_code_read_from_state(self):
        """Tool should use src_id from aoi_selection, not a separate parameter."""
        body = _make_fao_response("IDN", "extentOfForest")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = body

        state = _make_state(iso3="IDN", aoi_name="Indonesia")

        with patch("src.agent.tools.fao_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            command = await query_fra_data.ainvoke(_tool_call("forest_area", state=state))

        stats = command.update["statistics"]
        assert stats[0]["aoi_names"] == ["Indonesia"]
        assert all(r["country"] == "IDN" for r in stats[0]["data"]["data"])

    async def test_multi_aoi_combines_records(self):
        """Multiple AOIs should each be fetched and combined into one statistics entry."""
        def make_response(iso3):
            body = _make_fao_response(iso3, "extentOfForest")
            r = MagicMock()
            r.status_code = 200
            r.json.return_value = body
            return r

        state = {
            "aoi_selection": {
                "name": "Brazil + Indonesia",
                "aois": [
                    {"name": "Brazil", "src_id": "BRA", "source": "gadm", "subtype": "country"},
                    {"name": "Indonesia", "src_id": "IDN", "source": "gadm", "subtype": "country"},
                ],
            }
        }

        responses = [make_response("BRA"), make_response("IDN")]
        call_count = 0

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            r = responses[call_count]
            call_count += 1
            return r

        with patch("src.agent.tools.fao_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = mock_get
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            command = await query_fra_data.ainvoke(_tool_call("forest_area", state=state))

        stats = command.update["statistics"]
        assert len(stats) == 1
        all_records = stats[0]["data"]["data"]
        countries = {r["country"] for r in all_records}
        assert countries == {"BRA", "IDN"}
        assert stats[0]["aoi_names"] == ["Brazil", "Indonesia"]

    async def test_partial_aoi_failure_returns_partial_statistics(self):
        """If one AOI fails and another succeeds, return data for the successful one."""
        body = _make_fao_response("BRA", "extentOfForest")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = body

        call_count = 0

        async def mock_fetch(iso3, table, variables, year=None):
            nonlocal call_count
            call_count += 1
            if iso3 == "IDN":
                raise FAODataNotFoundError("IDN not found")
            from src.agent.tools.fao_client import _parse_response
            return _parse_response(body, iso3, table, year)

        state = {
            "aoi_selection": {
                "name": "Brazil + Indonesia",
                "aois": [
                    {"name": "Brazil", "src_id": "BRA", "source": "gadm", "subtype": "country"},
                    {"name": "Indonesia", "src_id": "IDN", "source": "gadm", "subtype": "country"},
                ],
            }
        }

        with patch("src.agent.tools.query_fra_data.fetch_fra_data", new=mock_fetch):
            command = await query_fra_data.ainvoke(_tool_call("forest_area", state=state))

        # Statistics should exist for BRA
        stats = command.update.get("statistics", [])
        assert len(stats) == 1
        countries = {r["country"] for r in stats[0]["data"]["data"]}
        assert countries == {"BRA"}
        # Tool message should mention the IDN failure
        msg = command.update["messages"][0].content
        assert "IDN not found" in msg


# ---------------------------------------------------------------------------
# variable_map sanity checks
# ---------------------------------------------------------------------------

class TestVariableMap:
    def test_all_valid_variables_are_strings(self):
        for v in VALID_VARIABLES:
            assert isinstance(v, str)

    def test_each_entry_has_required_keys(self):
        from src.agent.tools.variable_map import VARIABLE_MAP
        for name, config in VARIABLE_MAP.items():
            assert "table" in config, f"{name} missing 'table'"
            assert "variables" in config, f"{name} missing 'variables'"
            assert "unit" in config, f"{name} missing 'unit'"
            assert "description" in config, f"{name} missing 'description'"
