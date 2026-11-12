import json

from langchain_core.messages import AIMessage, ToolMessage

from src.agent.tools.analytics_mcp.area_names import names_seen

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
