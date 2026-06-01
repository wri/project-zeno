"""Unit tests for the FAO FRA HTTP client.

No network. Tests inject `httpx.MockTransport` directly into `FAOFRAClient`
— no monkey-patching of library internals required.

Structure:
- Constants
- parse_year_key and parse_response (pure domain logic, no HTTP)
- FAOFRAClient.build_source_url
- FAOFRAClient.fetch — HTTP behaviour (transport-injected)
"""

import httpx
import pytest

from src.agent.datasets.handlers import fao_fra_client
from src.agent.datasets.handlers.fao_fra_client import (
    FAOAPIError,
    FAODataNotFoundError,
    FAOFRAClient,
    FRA_REPORTING_YEARS,
    parse_response,
    parse_year_key,
)


def _ok_payload(iso3: str, table: str) -> dict:
    """Realistic minimal FAO response covering three reporting years."""
    return {
        "fra": {
            "2025": {
                iso3: {
                    table: {
                        "1990": {
                            "forestArea": {
                                "raw": "493538.00",
                                "odp": True,
                            },
                            "plantedForest": {
                                "raw": "5210.00",
                                "odp": False,
                            },
                        },
                        "2000": {
                            "forestArea": {
                                "raw": "483418.00",
                                "odp": True,
                            },
                        },
                        "2025": {
                            "forestArea": {
                                "raw": "462700.00",
                                "odp": True,
                            },
                        },
                    }
                }
            }
        }
    }


def _client_with(handler) -> FAOFRAClient:
    """Return a FAOFRAClient driven by the given MockTransport handler."""
    return FAOFRAClient(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_reporting_years_are_the_six_fra_snapshots():
    assert FRA_REPORTING_YEARS == [1990, 2000, 2010, 2015, 2020, 2025]


def test_module_constants_match_documented_base_url():
    assert fao_fra_client.BASE_URL == "https://fra-data.fao.org/api"
    assert fao_fra_client.ASSESSMENT_NAME == "fra"
    assert fao_fra_client.CYCLE_NAME == "2025"


# ---------------------------------------------------------------------------
# parse_year_key
# ---------------------------------------------------------------------------


def test_parse_year_key_single_year():
    assert parse_year_key("1990") == (1990, None)
    assert parse_year_key("2025") == (2025, None)


def test_parse_year_key_period_returns_end_year_and_label():
    year, label = parse_year_key("1990-2000")
    assert year == 2000
    assert label == "1990-2000"


def test_parse_year_key_raises_on_unrecognised_format():
    with pytest.raises(ValueError):
        parse_year_key("1990-2000-2010")


# ---------------------------------------------------------------------------
# parse_response — happy path and edge cases
# ---------------------------------------------------------------------------


def test_parse_response_flattens_years_and_variables():
    records = parse_response(
        _ok_payload("BRA", "extentOfForest"),
        iso3="BRA",
        table="extentOfForest",
        year=None,
    )
    # 3 years × variables present in each year (2 + 1 + 1)
    assert len(records) == 4
    sample = next(
        r
        for r in records
        if r["year"] == 1990 and r["variable"] == "forestArea"
    )
    assert sample == {
        "year": 1990,
        "period": None,
        "variable": "forestArea",
        "value": pytest.approx(493538.0),
        "odp": True,
        "country": "BRA",
    }


def test_parse_response_filters_by_year():
    records = parse_response(
        _ok_payload("BRA", "extentOfForest"),
        iso3="BRA",
        table="extentOfForest",
        year=2000,
    )
    assert [r["year"] for r in records] == [2000]


def test_parse_response_raises_on_missing_assessment():
    with pytest.raises(FAODataNotFoundError):
        parse_response({}, iso3="BRA", table="extentOfForest", year=None)


def test_parse_response_raises_on_missing_country():
    body = {"fra": {"2025": {"USA": {"extentOfForest": {}}}}}
    with pytest.raises(FAODataNotFoundError):
        parse_response(body, iso3="BRA", table="extentOfForest", year=None)


def test_parse_response_raises_on_missing_table():
    body = {"fra": {"2025": {"BRA": {"someOtherTable": {}}}}}
    with pytest.raises(FAODataNotFoundError):
        parse_response(body, iso3="BRA", table="extentOfForest", year=None)


def test_parse_response_coerces_non_numeric_value_to_none():
    body = {
        "fra": {
            "2025": {
                "BRA": {
                    "extentOfForest": {
                        "1990": {
                            "forestArea": {"raw": "not-a-number", "odp": False}
                        }
                    }
                }
            }
        }
    }
    records = parse_response(
        body, iso3="BRA", table="extentOfForest", year=None
    )
    assert records[0]["value"] is None


def test_parse_response_handles_period_keys_for_change_tables():
    """Rate-of-change tables key by period ('1990-2000'); the parser should
    surface the end year for the chart axis and preserve the period label."""
    body = {
        "fra": {
            "2025": {
                "BRA": {
                    "forestAreaChange": {
                        "1990-2000": {
                            "afforestation": {"raw": "100.0", "odp": True},
                            "deforestation": {"raw": "500.0", "odp": True},
                            "forestAreaNetChange": {
                                "raw": "-400.0",
                                "odp": True,
                            },
                        },
                        "2010-2015": {
                            "afforestation": {"raw": "120.0", "odp": True},
                            "deforestation": {"raw": "300.0", "odp": True},
                            "forestAreaNetChange": {
                                "raw": "-180.0",
                                "odp": True,
                            },
                        },
                    }
                }
            }
        }
    }
    records = parse_response(
        body, iso3="BRA", table="forestAreaChange", year=None
    )
    assert len(records) == 6  # 2 periods × 3 variables
    net_change = {
        r["period"]: r
        for r in records
        if r["variable"] == "forestAreaNetChange"
    }
    assert net_change["1990-2000"] == {
        "year": 2000,
        "period": "1990-2000",
        "variable": "forestAreaNetChange",
        "value": pytest.approx(-400.0),
        "odp": True,
        "country": "BRA",
    }
    assert net_change["2010-2015"]["year"] == 2015


def test_parse_response_period_is_none_for_snapshot_years():
    records = parse_response(
        _ok_payload("BRA", "extentOfForest"),
        iso3="BRA",
        table="extentOfForest",
        year=None,
    )
    assert all(r["period"] is None for r in records)


def test_parse_response_skips_non_year_keys_and_non_dict_nodes():
    body = {
        "fra": {
            "2025": {
                "BRA": {
                    "extentOfForest": {
                        "notAYear": {
                            "forestArea": {"raw": "1.0", "odp": False}
                        },
                        "2010": {
                            "forestArea": "not-a-dict",
                            "plantedForest": {"raw": "12.5", "odp": False},
                        },
                    }
                }
            }
        }
    }
    records = parse_response(
        body, iso3="BRA", table="extentOfForest", year=None
    )
    assert len(records) == 1
    assert records[0]["variable"] == "plantedForest"


# ---------------------------------------------------------------------------
# FAOFRAClient.build_source_url
# ---------------------------------------------------------------------------


def test_build_source_url_includes_iso3_and_table():
    url = FAOFRAClient().build_source_url("BRA", "extentOfForest")
    assert url.startswith("https://fra-data.fao.org/api/explorer/data?")
    assert "countryISOs[]=BRA" in url
    assert "tableNames[]=extentOfForest" in url
    assert "assessmentName=fra" in url


# ---------------------------------------------------------------------------
# FAOFRAClient.fetch — HTTP behaviour
# ---------------------------------------------------------------------------


async def test_fetch_returns_records_on_200():
    client = _client_with(
        lambda req: httpx.Response(
            200, json=_ok_payload("BRA", "extentOfForest")
        )
    )
    records = await client.fetch(
        "BRA", "extentOfForest", variables=["forestArea"]
    )
    assert len(records) >= 1


async def test_fetch_sends_correct_params():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=_ok_payload("BRA", "extentOfForest"))

    client = _client_with(handler)
    await client.fetch("BRA", "extentOfForest", variables=["forestArea"])

    assert captured["params"]["countryISOs[]"] == "BRA"
    assert captured["params"]["tableNames[]"] == "extentOfForest"
    assert captured["params"]["variables[]"] == "forestArea"
    assert captured["params"]["assessmentName"] == "fra"


async def test_fetch_sends_columns_param_for_year_filter():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=_ok_payload("BRA", "extentOfForest"))

    client = _client_with(handler)
    await client.fetch("BRA", "extentOfForest", variables=[], year=2000)
    assert captured["params"]["columns[]"] == "2000"


async def test_fetch_raises_api_error_on_5xx():
    client = _client_with(
        lambda req: httpx.Response(503, text="service down")
    )
    with pytest.raises(FAOAPIError):
        await client.fetch("BRA", "extentOfForest", variables=[])


async def test_fetch_raises_api_error_on_401():
    client = _client_with(lambda req: httpx.Response(401))
    with pytest.raises(FAOAPIError):
        await client.fetch("BRA", "extentOfForest", variables=[])


async def test_fetch_raises_not_found_on_4xx():
    client = _client_with(lambda req: httpx.Response(404))
    with pytest.raises(FAODataNotFoundError):
        await client.fetch("XXX", "extentOfForest", variables=[])


async def test_fetch_raises_api_error_on_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow")

    client = _client_with(handler)
    with pytest.raises(FAOAPIError):
        await client.fetch("BRA", "extentOfForest", variables=[])


async def test_fetch_raises_api_error_on_request_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    client = _client_with(handler)
    with pytest.raises(FAOAPIError):
        await client.fetch("BRA", "extentOfForest", variables=[])


async def test_fetch_raises_api_error_on_unparseable_body():
    client = _client_with(
        lambda req: httpx.Response(200, content=b"not-json")
    )
    with pytest.raises(FAOAPIError):
        await client.fetch("BRA", "extentOfForest", variables=[])
