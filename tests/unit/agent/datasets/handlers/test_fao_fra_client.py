"""Unit tests for the FAO FRA HTTP client.

No network. All HTTP is stubbed with httpx.MockTransport so the parsing,
URL composition, and error mapping are exercised end-to-end.
"""

import httpx
import pytest

from src.agent.datasets.handlers import fao_fra_client
from src.agent.datasets.handlers.fao_fra_client import (
    FRA_REPORTING_YEARS,
    FAOAPIError,
    FAODataNotFoundError,
    _build_source_url,
    _parse_response,
    fetch_fra_data,
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


def _patch_transport(monkeypatch, handler):
    """Replace httpx.AsyncClient with one driven by a MockTransport."""
    transport = httpx.MockTransport(handler)
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        return original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


# ---------------------------------------------------------------------------
# Constants and URL builder
# ---------------------------------------------------------------------------


def test_reporting_years_are_the_five_fra_snapshots():
    assert FRA_REPORTING_YEARS == [1990, 2000, 2010, 2015, 2020, 2025]


def test_build_source_url_includes_iso3_and_table():
    url = _build_source_url("BRA", "extentOfForest")
    assert url.startswith("https://fra-data.fao.org/api/explorer/data?")
    assert "countryISOs[]=BRA" in url
    assert "tableNames[]=extentOfForest" in url
    assert "assessmentName=fra" in url


# ---------------------------------------------------------------------------
# _parse_response — happy path and edge cases
# ---------------------------------------------------------------------------


def test_parse_response_flattens_years_and_variables():
    records = _parse_response(
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
    assert sample["value"] == pytest.approx(493538.0)
    assert sample["odp"] is True
    assert sample["country"] == "BRA"


def test_parse_response_filters_by_year():
    records = _parse_response(
        _ok_payload("BRA", "extentOfForest"),
        iso3="BRA",
        table="extentOfForest",
        year=2000,
    )
    assert [r["year"] for r in records] == [2000]


def test_parse_response_raises_on_missing_assessment():
    with pytest.raises(FAODataNotFoundError):
        _parse_response({}, iso3="BRA", table="extentOfForest", year=None)


def test_parse_response_raises_on_missing_country():
    body = {"fra": {"2025": {"USA": {"extentOfForest": {}}}}}
    with pytest.raises(FAODataNotFoundError):
        _parse_response(body, iso3="BRA", table="extentOfForest", year=None)


def test_parse_response_raises_on_missing_table():
    body = {"fra": {"2025": {"BRA": {"someOtherTable": {}}}}}
    with pytest.raises(FAODataNotFoundError):
        _parse_response(body, iso3="BRA", table="extentOfForest", year=None)


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
    records = _parse_response(
        body, iso3="BRA", table="extentOfForest", year=None
    )
    assert records[0]["value"] is None


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
    records = _parse_response(
        body, iso3="BRA", table="extentOfForest", year=None
    )
    # The non-year key is skipped; the non-dict variable is skipped; only
    # the plantedForest record survives.
    assert len(records) == 1
    assert records[0]["variable"] == "plantedForest"


# ---------------------------------------------------------------------------
# fetch_fra_data — HTTP behaviour
# ---------------------------------------------------------------------------


async def test_fetch_fra_data_returns_records_on_200(monkeypatch):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=_ok_payload("BRA", "extentOfForest"))

    _patch_transport(monkeypatch, handler)
    records = await fetch_fra_data(
        "BRA", "extentOfForest", variables=["forestArea"], year=None
    )

    assert len(records) >= 1
    assert "countryISOs%5B%5D=BRA" in captured["url"]
    assert "tableNames%5B%5D=extentOfForest" in captured["url"]
    assert "variables%5B%5D=forestArea" in captured["url"]


async def test_fetch_fra_data_passes_columns_for_year_filter(monkeypatch):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=_ok_payload("BRA", "extentOfForest"))

    _patch_transport(monkeypatch, handler)
    # year=2000 is present in _ok_payload so the response yields records
    await fetch_fra_data("BRA", "extentOfForest", variables=[], year=2000)
    assert "columns%5B%5D=2000" in captured["url"]


async def test_fetch_fra_data_raises_api_error_on_5xx(monkeypatch):
    _patch_transport(
        monkeypatch, lambda req: httpx.Response(503, text="service down")
    )
    with pytest.raises(FAOAPIError):
        await fetch_fra_data("BRA", "extentOfForest", variables=[])


async def test_fetch_fra_data_raises_api_error_on_401(monkeypatch):
    _patch_transport(monkeypatch, lambda req: httpx.Response(401))
    with pytest.raises(FAOAPIError):
        await fetch_fra_data("BRA", "extentOfForest", variables=[])


async def test_fetch_fra_data_raises_not_found_on_4xx(monkeypatch):
    _patch_transport(monkeypatch, lambda req: httpx.Response(404))
    with pytest.raises(FAODataNotFoundError):
        await fetch_fra_data("XXX", "extentOfForest", variables=[])


async def test_fetch_fra_data_raises_api_error_on_timeout(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow")

    _patch_transport(monkeypatch, handler)
    with pytest.raises(FAOAPIError):
        await fetch_fra_data("BRA", "extentOfForest", variables=[])


async def test_fetch_fra_data_raises_api_error_on_request_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    _patch_transport(monkeypatch, handler)
    with pytest.raises(FAOAPIError):
        await fetch_fra_data("BRA", "extentOfForest", variables=[])


async def test_fetch_fra_data_raises_api_error_on_unparseable_body(
    monkeypatch,
):
    _patch_transport(
        monkeypatch,
        lambda req: httpx.Response(200, content=b"not-json"),
    )
    with pytest.raises(FAOAPIError):
        await fetch_fra_data("BRA", "extentOfForest", variables=[])


def test_module_constants_match_documented_base_url():
    assert fao_fra_client.BASE_URL == "https://fra-data.fao.org/api"
    assert fao_fra_client.ASSESSMENT_NAME == "fra"
    assert fao_fra_client.CYCLE_NAME == "2025"
