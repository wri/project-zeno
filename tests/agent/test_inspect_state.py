import json

from langchain_core.messages import AIMessage, HumanMessage

from src.agent.tools.inspect_state import build_state_inspection


def test_build_state_inspection_summarizes_heavy_fields():
    state = {
        "user_persona": "Researcher",
        "aoi_selection": {
            "name": "Brazil states",
            "aois": [
                {
                    "name": "Acre",
                    "subtype": "state",
                    "source": "gadm",
                    "src_id": "BRA.1.1_1",
                    "bbox": [-73.99, -11.15, -66.62, -7.11],
                    "geometry": {"type": "Polygon", "coordinates": [[[0, 0]]]},
                }
            ],
        },
        "statistics": [
            {
                "id": "stat-1",
                "dataset_name": "tree cover loss",
                "start_date": "2020-01-01",
                "end_date": "2024-01-01",
                "source_url": "https://example.com/data",
                "data": {},
                "aoi_names": ["Acre"],
            }
        ],
        "charts_data": [
            {
                "id": "chart_0",
                "title": "Loss over time",
                "type": "line",
                "data": [
                    {"year": 2020, "value": 1.2},
                    {"year": 2021, "value": 2.3},
                ],
            }
        ],
        "messages": [
            HumanMessage(content="Show loss in Acre"),
            AIMessage(content="x" * 1000),
        ],
    }

    inspection = build_state_inspection(state)

    assert inspection["user_persona"] == "Researcher"
    assert inspection["aoi_selection"]["aois"] == [
        {
            "name": "Acre",
            "subtype": "state",
            "source": "gadm",
            "src_id": "BRA.1.1_1",
        }
    ]
    assert inspection["statistics"][0]["data"] == (
        "(empty — use source_url to fetch full result)"
    )
    assert inspection["charts_data"][0]["data"]["row_count"] == 2
    assert inspection["messages"]["count"] == 2
    assert len(inspection["messages"]["recent"][1]["content"]) < 400


def test_build_state_inspection_fields_filter_and_tabular_summary():
    state = {
        "dataset": {"dataset_name": "tree cover loss", "dataset_id": 4},
        "statistics": [
            {
                "dataset_name": "tree cover loss",
                "start_date": "2020-01-01",
                "end_date": "2024-01-01",
                "data": {
                    "aoi_id": ["a", "b", "c"],
                    "umid": [1.0, 2.0, 3.0],
                },
                "aoi_names": ["A", "B", "C"],
            }
        ],
    }

    inspection = build_state_inspection(
        state, fields=["dataset", "statistics", "missing"]
    )

    assert set(inspection.keys()) == {
        "dataset",
        "statistics",
        "_unknown_fields",
    }
    assert inspection["_unknown_fields"] == ["missing"]
    assert inspection["statistics"][0]["data"] == {
        "columns": ["aoi_id", "umid"],
        "row_count": 3,
    }


def test_inspect_state_tool_returns_json():
    from src.agent.tools.inspect_state import inspect_state

    payload = json.loads(
        inspect_state.invoke(
            {
                "fields": ["user_persona"],
                "state": {"user_persona": "Analyst"},
            }
        )
    )
    assert payload == {"user_persona": "Analyst"}
