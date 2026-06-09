from importlib import import_module
from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.agent.subagents.pick_aoi import Geocoder, pick_aoi
from src.agent.subagents.pick_aoi.tool import (
    AOIIndex,
    PlaceQuery,
    _antimeridian_bbox_sql,
    fetch_aoi_bbox,
)


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
async def test_fetch_aoi_bbox_uses_custom_bbox_sql_for_custom_source(
    monkeypatch,
):
    captured = {}
    tool_module = import_module("src.agent.subagents.pick_aoi.tool")

    class _FakeConn:
        async def execute(self, query, params=None):
            captured["sql"] = str(query)
            result = MagicMock()
            result.fetchone.return_value = ([1.0, 2.0, 3.0, 4.0],)
            return result

    class _FakeConnContext:
        async def __aenter__(self):
            return _FakeConn()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    def fake_pool():
        return _FakeConnContext()

    monkeypatch.setattr(tool_module, "get_connection_from_pool", fake_pool)

    await fetch_aoi_bbox("custom", "some-uuid")

    assert "jsonb_array_elements_text" in captured["sql"]
    assert "custom_areas" in captured["sql"]


@pytest.mark.asyncio
async def test_fetch_aoi_bbox_no_row_returns_default(monkeypatch):
    tool_module = import_module("src.agent.subagents.pick_aoi.tool")

    class _FakeConn:
        async def execute(self, query, params=None):
            result = MagicMock()
            result.fetchone.return_value = None
            return result

    class _FakeConnContext:
        async def __aenter__(self):
            return _FakeConn()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    def fake_pool():
        return _FakeConnContext()

    monkeypatch.setattr(tool_module, "get_connection_from_pool", fake_pool)

    result = await fetch_aoi_bbox("gadm", "NONEXISTENT")

    assert result == [-180.0, -90.0, 180.0, 90.0]


# ---------------------------------------------------------------------------
# pick_aoi tool / Geocoder wiring — the thin tool delegates to the geocoding
# subagent, which extracts place(s) from the question then looks them up.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pick_aoi_tool_resolves_via_geocoder(monkeypatch):
    """The tool takes only `question`: the subagent extracts the place,
    then runs the DB lookup. No places/subregion args from the caller."""
    tool_module = import_module("src.agent.subagents.pick_aoi.tool")

    async def fake_extract(self, question):
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
            "args": {"question": "tree cover loss in Para, Brazil"},
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
    """If the request names no place, the subagent returns a clarifying
    question instead of touching the database."""

    async def fake_extract(self, question):
        return PlaceQuery(places=[], subregion=None)

    monkeypatch.setattr(Geocoder, "extract", fake_extract)

    command = await pick_aoi.ainvoke(
        {
            "args": {"question": "show me tree cover loss"},
            "id": "tc-2",
            "type": "tool_call",
        }
    )

    assert "aoi_selection" not in command.update
    assert "couldn't identify a place" in str(
        command.update["messages"][0].content
    )
