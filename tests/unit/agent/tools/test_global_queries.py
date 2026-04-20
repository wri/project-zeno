"""Unit tests for global_queries — no DB, no LLM."""

import re
from importlib import import_module
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest

from src.agent.tools.pick_aoi.global_queries import (
    GLOBAL_AOI_SELECTION_NAME,
    GLOBAL_TRIGGER_WORDS,
    _query_all_countries,
    handle_global_request,
    is_global_request,
)
from src.shared.geocoding_helpers import GADM_STANDARD_ID_RE


@pytest.mark.parametrize("word", sorted(GLOBAL_TRIGGER_WORDS))
def test_is_global_request_recognises_trigger_words(word):
    assert is_global_request([word]) is True


@pytest.mark.parametrize("word", sorted(GLOBAL_TRIGGER_WORDS))
def test_is_global_request_case_insensitive(word):
    assert is_global_request([word.upper()]) is True
    assert is_global_request([word.capitalize()]) is True


def test_is_global_request_strips_whitespace():
    assert is_global_request(["  global  "]) is True


def test_is_global_request_false_for_regular_place():
    assert is_global_request(["Brazil"]) is False
    assert is_global_request(["Brazil", "Peru"]) is False


def test_is_global_request_true_if_any_place_matches():
    assert is_global_request(["Brazil", "global"]) is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "subregion", [None, "state", "kba", "wdpa", "landmark"]
)
async def test_handle_global_request_rejects_non_country_subregion(subregion):
    cmd = await handle_global_request(subregion, tool_call_id="tc-1")
    msg = cmd.update["messages"][0]
    assert "country" in msg.content.lower()


_SAMPLE_ISOS = [
    "USA",
    "BRA",
    "IND",
    "DEU",
    "FRA",
    "GBR",
    "JPN",
    "CHN",
    "AUS",
    "CAN",
]


def _make_country_df(n: int = 1) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "name": f"Country {i}",
                "subtype": "country",
                "src_id": _SAMPLE_ISOS[i % len(_SAMPLE_ISOS)],
                "source": "gadm",
            }
            for i in range(n)
        ]
    )


@pytest.mark.asyncio
async def test_handle_global_request_returns_all_countries():
    df = _make_country_df(5)
    with patch(
        "src.agent.tools.pick_aoi.global_queries._query_all_countries",
        new=AsyncMock(return_value=df),
    ):
        cmd = await handle_global_request("country", tool_call_id="tc-2")

    aoi_selection = cmd.update["aoi_selection"]
    assert aoi_selection["name"] == GLOBAL_AOI_SELECTION_NAME
    assert len(aoi_selection["aois"]) == 5


@pytest.mark.asyncio
async def test_handle_global_request_sets_gadm_id_on_each_aoi():
    df = _make_country_df(2)
    with patch(
        "src.agent.tools.pick_aoi.global_queries._query_all_countries",
        new=AsyncMock(return_value=df),
    ):
        cmd = await handle_global_request("country", tool_call_id="tc-3")

    for aoi in cmd.update["aoi_selection"]["aois"]:
        assert "gadm_id" in aoi


@pytest.mark.asyncio
async def test_handle_global_request_tool_message_text():
    df = _make_country_df(2)
    with patch(
        "src.agent.tools.pick_aoi.global_queries._query_all_countries",
        new=AsyncMock(return_value=df),
    ):
        cmd = await handle_global_request("country", tool_call_id="tc-4")

    msg = cmd.update["messages"][0]
    assert "countries" in msg.content.lower()


@pytest.mark.parametrize(
    "gadm_id",
    ["USA", "BRA", "IND", "BRA.16_1", "IND.12.26_1", "USA.1.2.3_2"],
)
def test_gadm_standard_id_re_accepts_valid_ids(gadm_id):
    assert re.search(GADM_STANDARD_ID_RE, gadm_id)


@pytest.mark.parametrize(
    "gadm_id",
    ["Z01", "Z02", "Z09", "Z01.1_1", "Z09.3.2_1"],
)
def test_gadm_standard_id_re_rejects_disputed_territory_ids(gadm_id):
    assert not re.search(GADM_STANDARD_ID_RE, gadm_id)


@pytest.mark.asyncio
async def test_query_all_countries_uses_global_bbox_expression(monkeypatch):
    captured = {}
    expected_df = _make_country_df()
    global_queries_module = import_module(
        "src.agent.tools.pick_aoi.global_queries"
    )

    class _FakeConn:
        async def run_sync(self, fn):
            return fn("sync-conn")

    class _FakeConnContext:
        async def __aenter__(self):
            return _FakeConn()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    def fake_pool():
        return _FakeConnContext()

    def fake_read_sql(sql, sync_conn, params):
        captured["sql"] = str(sql)
        captured["sync_conn"] = sync_conn
        captured["params"] = params
        return expected_df

    monkeypatch.setattr(
        global_queries_module, "get_connection_from_pool", fake_pool
    )
    monkeypatch.setattr(pd, "read_sql", fake_read_sql)

    result = await _query_all_countries()

    assert result.equals(expected_df)
    assert captured["sync_conn"] == "sync-conn"
    assert captured["params"] == {"subtype": "country"}
    assert (
        "json_build_array(-180.0, -90.0, 180.0, 90.0) AS bbox"
        in captured["sql"]
    )
