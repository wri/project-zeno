from importlib import import_module
from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.agent.subagents.pick_aoi import Geocoder, pick_aoi
from src.agent.subagents.pick_aoi.tool import AOIIndex, PlaceQuery
from src.shared import geocoding_helpers
from src.shared.geocoding_helpers import (
    _antimeridian_bbox_sql,
    fetch_aoi_bbox,
)


def _fake_conn_context(captured, row):
    """A pooled-connection stand-in that records the SQL and returns *row*."""

    class _FakeConn:
        async def execute(self, query, params=None):
            captured["sql"] = str(query)
            captured["params"] = params
            result = MagicMock()
            result.fetchone.return_value = row
            return result

    class _FakeConnContext:
        async def __aenter__(self):
            return _FakeConn()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    return _FakeConnContext()


def test_sql_contains_crossing_condition():
    sql = _antimeridian_bbox_sql("geometry")
    assert "ST_XMax(geometry) - ST_XMin(geometry) > 180" in sql


def test_sql_clips_to_east_and_west_half_planes():
    sql = _antimeridian_bbox_sql("geometry")
    assert "ST_MakeEnvelope(0, -90, 180, 90, 4326)" in sql
    assert "ST_MakeEnvelope(-180, -90, 0, 90, 4326)" in sql


def test_sql_has_fallback_branch():
    sql = _antimeridian_bbox_sql("geometry")
    assert "ELSE json_build_array" in sql


def test_sql_custom_geom_expr():
    sql = _antimeridian_bbox_sql("bounds.geometry")
    assert "bounds.geometry" in sql
    assert "geometry" not in sql.replace("bounds.geometry", "")


def test_sql_uses_west_xmin_and_east_xmax():
    sql = _antimeridian_bbox_sql("geometry")
    assert "ST_XMin(ST_Envelope(ST_ClipByBox2D" in sql
    assert "ST_XMax(ST_Envelope(ST_ClipByBox2D" in sql


@pytest.mark.asyncio
async def test_fetch_aoi_bbox_unknown_source_returns_default():
    result = await fetch_aoi_bbox("unknown_source", "some_id")
    assert result == [-180.0, -90.0, 180.0, 90.0]


@pytest.mark.asyncio
async def test_fetch_aoi_bbox_reads_precomputed_bbox_for_every_source(
    monkeypatch,
):
    """One query over aois, whatever the source -- no per-source bbox SQL."""
    captured = {}

    def fake_pool():
        return _fake_conn_context(captured, ([1.0, 2.0, 3.0, 4.0],))

    monkeypatch.setattr(
        geocoding_helpers, "get_connection_from_pool", fake_pool
    )

    for source in ("custom", "gadm", "kba"):
        assert await fetch_aoi_bbox(source, "some-id") == [
            1.0,
            2.0,
            3.0,
            4.0,
        ]
        assert "FROM aois" in captured["sql"]
        assert captured["params"] == {"source": source, "src_id": "some-id"}
        # The antimeridian CASE ran per row before; bbox is now precomputed.
        assert "ST_ClipByBox2D" not in captured["sql"]


@pytest.mark.asyncio
async def test_fetch_aoi_bbox_no_row_returns_default(monkeypatch):
    def fake_pool():
        return _fake_conn_context({}, None)

    monkeypatch.setattr(
        geocoding_helpers, "get_connection_from_pool", fake_pool
    )

    result = await fetch_aoi_bbox("gadm", "NONEXISTENT")

    assert result == [-180.0, -90.0, 180.0, 90.0]


@pytest.mark.asyncio
async def test_fetch_aoi_bbox_null_bbox_returns_default(monkeypatch):
    """aois.bbox is nullable; a null must not reach the AOI's bbox field."""

    def fake_pool():
        return _fake_conn_context({}, (None,))

    monkeypatch.setattr(
        geocoding_helpers, "get_connection_from_pool", fake_pool
    )

    assert await fetch_aoi_bbox("gadm", "BRA") == [-180.0, -90.0, 180.0, 90.0]


# ---------------------------------------------------------------------------
# pick_aoi tool / Geocoder wiring — the thin tool delegates to the geocoding
# subagent, which extracts place(s) from the question then looks them up.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pick_aoi_tool_resolves_via_geocoder(monkeypatch):
    """The tool takes only `question`: the subagent extracts the place,
    then runs the DB lookup. No places/subregion args from the caller."""
    tool_module = import_module("src.agent.subagents.pick_aoi.tool")

    async def fake_extract(self, question, aoi_type):
        return PlaceQuery(places=["Para, Brazil"], subregion=None)

    async def fake_query_aoi_database(place_name, aoi_type, result_limit=10):
        return pd.DataFrame(
            [
                {
                    "src_id": "BRA.14_1",
                    "name": "Para, Brazil",
                    "subtype": "state-province",
                    "source": "gadm",
                }
            ]
        )

    async def fake_select_best_aoi(question, candidate_aois):
        return AOIIndex(
            src_id="BRA.14_1",
            name="Para, Brazil",
            subtype="state-province",
            source="gadm",
        )

    monkeypatch.setattr(Geocoder, "extract", fake_extract)
    monkeypatch.setattr(
        tool_module, "query_aoi_database", fake_query_aoi_database
    )
    monkeypatch.setattr(tool_module, "select_best_aoi", fake_select_best_aoi)

    command = await pick_aoi.ainvoke(
        {
            "args": {
                "question": "tree cover loss in Para, Brazil",
                "area_of_interest": "adminstrative area (country, state/region, country/subregion)",
                "state": {},
            },
            "id": "tc-1",
            "type": "tool_call",
        }
    )

    selection = command.update["aoi_selection"]
    assert selection["name"] == "Para, Brazil"
    assert selection["aois"][0]["src_id"] == "BRA.14_1"


@pytest.mark.asyncio
async def test_pick_aoi_tool_asks_for_clarification_when_no_place(
    monkeypatch,
):
    async def fake_extract(self, question, aoi_type):
        return PlaceQuery(places=[], subregion=None)

    monkeypatch.setattr(Geocoder, "extract", fake_extract)

    command = await pick_aoi.ainvoke(
        {
            "args": {
                "question": "show me tree cover loss",
                "area_of_interest": None,
                "state": {},
            },
            "id": "tc-2",
            "type": "tool_call",
        }
    )

    assert "aoi_selection" not in command.update
    assert "couldn't identify a place" in str(
        command.update["messages"][0].content
    )


@pytest.mark.asyncio
async def test_select_best_aoi_empty_candidates_returns_none():
    """When DB search returns zero rows, select_best_aoi should return None
    instead of crashing with 'single positional indexer is out-of-bounds'."""
    from src.agent.subagents.pick_aoi.tool import select_best_aoi

    result = await select_best_aoi("some question", pd.DataFrame())
    assert result is None


@pytest.mark.asyncio
async def test_select_best_aoi_bad_src_id_returns_none(monkeypatch):
    """When the LLM picks a src_id that isn't among the candidates,
    select_best_aoi should return None instead of crashing on .iloc[0]."""
    tool_module = import_module("src.agent.subagents.pick_aoi.tool")

    async def fake_structured_output(_input):
        return tool_module.AOIId(src_id="does-not-exist")

    class _FakeSmallModel:
        def with_structured_output(self, schema):
            return fake_structured_output

    monkeypatch.setattr(tool_module, "SMALL_MODEL", _FakeSmallModel())

    candidates = pd.DataFrame(
        [
            {
                "src_id": "BRA.14_1",
                "name": "Para, Brazil",
                "subtype": "state-province",
                "source": "gadm",
            }
        ]
    )
    result = await tool_module.select_best_aoi("some question", candidates)
    assert result is None


@pytest.mark.asyncio
async def test_pick_aoi_returns_no_match_when_db_search_empty(monkeypatch):
    """When the DB returns no candidates, pick_aoi should return a helpful
    message instead of crashing."""
    tool_module = import_module("src.agent.subagents.pick_aoi.tool")

    async def fake_extract(self, question, aoi_type):
        return PlaceQuery(places=["Nonexistent Place"], subregion=None)

    async def fake_query_aoi_database(place_name, aoi_type, result_limit=10):
        return pd.DataFrame()  # empty results

    monkeypatch.setattr(Geocoder, "extract", fake_extract)
    monkeypatch.setattr(
        tool_module, "query_aoi_database", fake_query_aoi_database
    )

    command = await pick_aoi.ainvoke(
        {
            "args": {
                "question": "trees around Nonexistent Place",
                "area_of_interest": None,
                "state": {},
            },
            "id": "tc-3",
            "type": "tool_call",
        }
    )

    assert "aoi_selection" not in command.update
    assert (
        "no matching location"
        in str(command.update["messages"][0].content).lower()
    )


@pytest.mark.asyncio
async def test_pick_aoi_reports_unmatched_places_alongside_matches(
    monkeypatch,
):
    """When some places match and others don't, pick_aoi should still return
    the matches but name the place(s) it couldn't find rather than silently
    dropping them."""
    tool_module = import_module("src.agent.subagents.pick_aoi.tool")

    async def fake_extract(self, question, aoi_type):
        return PlaceQuery(
            places=["Para, Brazil", "Nonexistent Place"], subregion=None
        )

    async def fake_query_aoi_database(place_name, aoi_type, result_limit=10):
        if place_name == "Para, Brazil":
            return pd.DataFrame(
                [
                    {
                        "src_id": "BRA.14_1",
                        "name": "Para, Brazil",
                        "subtype": "state-province",
                        "source": "gadm",
                    }
                ]
            )
        return pd.DataFrame()

    async def fake_select_best_aoi(question, candidate_aois):
        if candidate_aois.empty:
            return None
        return AOIIndex(
            src_id="BRA.14_1",
            name="Para, Brazil",
            subtype="state-province",
            source="gadm",
        )

    monkeypatch.setattr(Geocoder, "extract", fake_extract)
    monkeypatch.setattr(
        tool_module, "query_aoi_database", fake_query_aoi_database
    )
    monkeypatch.setattr(tool_module, "select_best_aoi", fake_select_best_aoi)

    command = await pick_aoi.ainvoke(
        {
            "args": {
                "question": (
                    "tree cover loss in Para, Brazil and Nonexistent Place"
                ),
                "area_of_interest": None,
                "state": {},
            },
            "id": "tc-4",
            "type": "tool_call",
        }
    )

    selection = command.update["aoi_selection"]
    assert selection["aois"][0]["src_id"] == "BRA.14_1"
    assert "Nonexistent Place" in str(command.update["messages"][0].content)
