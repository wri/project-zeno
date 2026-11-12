import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from src.agent.tools.analytics_mcp.state_adapters.aoi_selection import (
    UnsupportedAreaError,
    area_selection_entry,
    names_seen,
)


def match(aoi_type: str, aoi_id: str, display_name: str = "Somewhere") -> dict:
    return {
        "name": display_name.split(",")[0],
        "display_name": display_name,
        "aoi": {"type": aoi_type, "ids": [aoi_id]},
    }


def test_country_keeps_its_id():
    entry = area_selection_entry(match("admin", "BRA", "Brazil"))

    assert entry["source"] == "gadm"
    assert entry["src_id"] == "BRA"
    assert entry["gadm_id"] == "BRA"
    assert entry["subtype"] == "country"
    assert entry["name"] == "Brazil"


def test_subnational_admin_gets_the_gadm_version_suffix():
    entry = area_selection_entry(match("admin", "BRA.14.3", "Novo Progresso"))

    assert entry["src_id"] == "BRA.14.3_1"
    assert entry["subtype"] == "district-county"


def test_named_area_uses_its_own_source():
    entry = area_selection_entry(match("key_biodiversity_area", "12345"))

    assert entry["source"] == "kba"
    assert entry["src_id"] == "12345"
    assert entry["sitrecid"] == "12345"
    assert entry["subtype"] == "key-biodiversity-area"


def test_unknown_area_type_is_rejected():
    with pytest.raises(UnsupportedAreaError):
        area_selection_entry(match("custom_aoi", "abc"))


SUBREGIONS = {
    "total": 2,
    "areas": [
        {"name": "Nigeria", "aoi": {"type": "admin", "ids": ["NGA"]}},
        {"name": "Ghana", "aoi": {"type": "admin", "ids": ["GHA"]}},
    ],
}
PICKED = {
    "selected": [
        {"name": "Pará, Brazil", "aoi": {"type": "admin", "ids": ["BRA.14"]}}
    ],
    "other_matches": {
        "Pará": [
            {
                "name": "Para, Suriname",
                "aoi": {"type": "admin", "ids": ["SUR.6"]},
            }
        ]
    },
}


def test_names_come_from_earlier_area_results():
    messages = [
        AIMessage("Looking up areas"),
        ToolMessage(json.dumps(SUBREGIONS), tool_call_id="1"),
        ToolMessage(json.dumps(PICKED), tool_call_id="2"),
        ToolMessage("Successfully pulled data", tool_call_id="3"),
    ]

    assert names_seen(messages) == {
        "NGA": "Nigeria",
        "GHA": "Ghana",
        "BRA.14": "Pará, Brazil",
        "SUR.6": "Para, Suriname",
    }
