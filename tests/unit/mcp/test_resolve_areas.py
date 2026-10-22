"""resolve_areas: the geocoder's deterministic half, over MCP.

The search is patched the way the pick_aoi tests patch it, so these pin
what the MCP tool makes of each Geocoder.lookup outcome.
"""

import pandas as pd
import pytest
from fastmcp import Client

from src.agent.config import AgentSettings
from src.mcp.server import mcp_server
from src.shared.request_context import bound_user_id
from tests.unit.agent.tools.pick_aoi.conftest import (
    _patch_search,
    _row,
    _SmallModelStub,
    tool_module,
)

PARA = _row("BRA.14_1", "Pará, Brazil", subtype="state-province", score=0.9)
CORDOBA_ARG = _row(
    "ARG.6_1", "Córdoba, Argentina", subtype="state-province", leaf="Córdoba"
)
CORDOBA_ESP = _row(
    "ESP.2_1", "Córdoba, Spain", subtype="state-province", leaf="Córdoba"
)


async def _resolve(args: dict):
    async with Client(mcp_server) as client:
        return await client.call_tool("resolve_areas", args)


async def test_a_place_resolves_to_its_area_without_a_model(monkeypatch):
    _patch_search(monkeypatch, {"Para, Brazil": [PARA]})
    # The kill switch would hand the pick to a model; the tool overrides it.
    monkeypatch.setattr(AgentSettings, "aoi_normalizer_enabled", False)
    monkeypatch.setattr(tool_module, "SMALL_MODEL", _SmallModelStub())

    result = await _resolve({"places": [{"place": "Para, Brazil"}]})

    assert [a["aoi_id"] for a in result.structured_content["areas"]] == [
        "gadm:BRA.14_1"
    ]
    assert result.structured_content["candidates"] == []
    assert "gadm:BRA.14_1: Pará, Brazil (state-province)" in (
        result.content[0].text
    )


async def test_a_name_in_two_countries_returns_candidates(monkeypatch):
    _patch_search(monkeypatch, {"Cordoba": [CORDOBA_ARG, CORDOBA_ESP]})

    result = await _resolve({"places": [{"place": "Cordoba"}]})

    structured = result.structured_content
    assert structured["areas"] == []
    assert {c["aoi_id"] for c in structured["candidates"]} == {
        "gadm:ARG.6_1",
        "gadm:ESP.2_1",
    }
    text = result.content[0].text
    assert "Ask the user which one they mean" in text
    # The agent's note about its own nudge does not reach an MCP client.
    assert "send_nudge" not in text


async def test_no_match_says_so_and_selects_nothing(monkeypatch):
    _patch_search(monkeypatch, {})

    result = await _resolve({"places": [{"place": "Atlantis"}]})

    assert result.structured_content["areas"] == []
    assert "No matching location was found for: Atlantis" in (
        result.content[0].text
    )


async def test_a_subregion_expands_into_its_parts(monkeypatch):
    _patch_search(
        monkeypatch,
        {"Odisha, India": [_row("IND.26_1", "Odisha, India", score=0.9)]},
    )
    asked = []

    async def fake_subregions(subregion_name, source, src_id):
        asked.append((subregion_name, source, src_id))
        return pd.DataFrame(
            [
                {
                    "name": f"District {i}, Odisha, India",
                    "subtype": "district-county",
                    "source": "gadm",
                    "src_id": f"IND.26.{i}_1",
                    "bbox": [84.0, 20.0, 85.0, 21.0],
                }
                for i in (1, 2)
            ]
        )

    monkeypatch.setattr(
        tool_module, "query_subregion_database", fake_subregions
    )

    result = await _resolve(
        {"places": [{"place": "Odisha, India"}], "subregion": "district"}
    )

    assert asked == [("district", "gadm", "IND.26_1")]
    assert [a["aoi_id"] for a in result.structured_content["areas"]] == [
        "gadm:IND.26.1_1",
        "gadm:IND.26.2_1",
    ]


async def test_the_search_leaves_custom_areas_out_without_a_user(
    monkeypatch,
):
    calls = []

    async def fake_search_aois(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame()

    monkeypatch.setattr(tool_module, "search_aois", fake_search_aois)

    await tool_module.query_aoi_database("Para", None)
    with bound_user_id("u1"):
        await tool_module.query_aoi_database("Para", None)

    assert [call["include_custom"] for call in calls] == [False, True]


@pytest.mark.parametrize("places", [[], [{"place": "x"}] * 11])
async def test_the_number_of_places_is_bounded(places):
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "resolve_areas", {"places": places}, raise_on_error=False
        )
    assert result.is_error


@pytest.mark.parametrize(
    "place",
    [
        {"place": "Para", "alternatives": ["a", "b", "c", "d"]},
        {"place": "x" * 201},
        {"place": "Para", "canonical": "x" * 201},
        {"place": "Para", "alternatives": ["x" * 201]},
    ],
)
async def test_the_spellings_of_a_place_are_bounded(place):
    # Each spelling is its own query, so a client cannot ask for thousands.
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "resolve_areas", {"places": [place]}, raise_on_error=False
        )
    assert result.is_error
