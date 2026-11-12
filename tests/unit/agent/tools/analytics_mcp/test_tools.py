import json
from typing import Any

import pytest
from langchain_core.messages import ToolMessage

from src.agent.tools.analytics_mcp.client import AnalyticsMcpError
from src.agent.tools.analytics_mcp.dataset_ids import DatasetIds
from src.agent.tools.analytics_mcp.payload_choices import PayloadChoices
from src.agent.tools.analytics_mcp.tools import AnalyticsMcpTools

LINK = "https://analytics.example/v0/land_change/tree_cover_loss/analytics/abc"
PARA = {
    "name": "Pará",
    "display_name": "Pará, Brazil",
    "aoi": {"type": "admin", "ids": ["BRA.14"]},
}
PARA_SELECTION = {
    "name": "Pará, Brazil",
    "aois": [
        {
            "source": "gadm",
            "src_id": "BRA.14_1",
            "gadm_id": "BRA.14_1",
            "name": "Pará, Brazil",
            "subtype": "state-province",
        }
    ],
}
PAYLOAD = {"aoi": PARA["aoi"], "start_year": "2015", "end_year": "2024"}


class FakeMcp:
    """Answers each tool with queued responses, or raises queued errors."""

    def __init__(self, responses: dict[str, list[Any]]):
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    async def call(self, tool: str, arguments: dict) -> Any:
        self.calls.append((tool, arguments))
        response = self.responses[tool].pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class RecordedStatistics:
    def __init__(self):
        self.saved: list[dict] = []

    async def record(self, statistics: dict) -> str:
        self.saved.append(statistics)
        return "statistics-1"


class FakeDatasets:
    async def selection(
        self,
        dataset_id: int,
        context_layer: str | None = None,
        canopy_cover: int | None = None,
    ) -> dict:
        parameters = None
        if canopy_cover is not None:
            parameters = [{"name": "canopy_cover", "values": [canopy_cover]}]
        return {
            "dataset_id": dataset_id,
            "dataset_name": "Tree cover loss",
            "cautions": "Loss is not deforestation.",
            "start_date": "2001-01-01",
            "end_date": "2025-12-31",
            "context_layer": context_layer,
            "parameters": parameters,
        }


async def no_wait(seconds: float) -> None:
    return None


def build_tools(mcp: FakeMcp, recorder: RecordedStatistics | None = None):
    return AnalyticsMcpTools(
        mcp=mcp,
        dataset_ids=DatasetIds(
            catalog=[
                {
                    "dataset_id": 4,
                    "analytics_api_endpoint": "/v0/land_change/tree_cover_loss/analytics",
                }
            ],
            intersection_ids={},
            alias_ids={"deforestation": 4},
        ),
        datasets=FakeDatasets(),
        payload_choices=PayloadChoices(
            default_canopy_cover=30, natural_forest_canopy_cover=10
        ),
        record_statistics=(recorder or RecordedStatistics()).record,
        sleep=no_wait,
        poll_timeout_seconds=180,
    )


def analysis(status: str, result: dict | None = None) -> dict:
    return {
        "link": LINK,
        "status": status,
        "message": "",
        "retry_after_seconds": 1,
        "result": result,
        "metadata": None,
    }


async def test_pick_aoi_selects_the_best_match():
    second = {**PARA, "display_name": "Pará, Suriname"}
    tools = build_tools(FakeMcp({"search_areas": [[PARA, second]]}))

    command = await tools.pick_aoi(["Pará"], state={}, tool_call_id="call-1")

    assert command.update["aoi_selection"] == PARA_SELECTION
    message = command.update["messages"][0].content
    assert '"ids": ["BRA.14"]' in message
    assert "Pará, Suriname" in message


async def test_pick_aoi_selects_every_place_in_one_selection():
    acre = {
        "name": "Acre",
        "display_name": "Acre, Brazil",
        "aoi": {"type": "admin", "ids": ["BRA.1"]},
    }
    mcp = FakeMcp({"search_areas": [[PARA], [acre]]})

    command = await build_tools(mcp).pick_aoi(
        ["Pará", "Acre"], state={}, tool_call_id="call-1"
    )

    selection = command.update["aoi_selection"]
    assert [area["src_id"] for area in selection["aois"]] == [
        "BRA.14_1",
        "BRA.1_1",
    ]
    assert selection["name"] == "Pará, Brazil, Acre, Brazil"
    assert [call[1]["name"] for call in mcp.calls] == ["Pará", "Acre"]


async def test_pick_aoi_selects_the_places_found_and_names_the_rest():
    mcp = FakeMcp({"search_areas": [[PARA], []]})

    command = await build_tools(mcp).pick_aoi(
        ["Pará", "Atlantis"], state={}, tool_call_id="call-1"
    )

    assert len(command.update["aoi_selection"]["aois"]) == 1
    assert "Atlantis" in command.update["messages"][0].content


async def test_pick_aoi_without_matches_changes_nothing():
    tools = build_tools(FakeMcp({"search_areas": [[]]}))

    command = await tools.pick_aoi(
        ["Atlantis"], state={}, tool_call_id="call-1"
    )

    assert "aoi_selection" not in command.update
    assert command.update["messages"][0].response_metadata == {
        "msg_type": "human_feedback"
    }


async def test_pick_dataset_selects_the_catalog_dataset():
    detail = {
        "name": "tree_cover_loss",
        "description": "# Primary Dataset ... a long dataset card",
        "request_schema": {"title": "Payload"},
    }
    tools = build_tools(FakeMcp({"describe_dataset": [detail]}))

    command = await tools.pick_dataset(
        "tree_cover_loss", tool_call_id="call-1"
    )

    dataset = command.update["dataset"]
    assert dataset["dataset_id"] == 4
    assert dataset["analytics_dataset"] == "tree_cover_loss"
    assert dataset["dataset_name"] == "Tree cover loss"
    assert dataset["cautions"] == "Loss is not deforestation."
    content = command.update["messages"][0].content
    assert '"title": "Payload"' in content
    assert "Loss is not deforestation." in content
    assert "dataset card" not in content


async def test_pick_dataset_reports_an_unknown_dataset():
    unknown = AnalyticsMcpError("Unknown dataset 'carbon_flux'")
    tools = build_tools(FakeMcp({"describe_dataset": [unknown]}))

    command = await tools.pick_dataset("carbon_flux", tool_call_id="call-1")

    assert "dataset" not in command.update


async def test_pull_data_waits_for_the_analysis_and_records_statistics():
    result = {"aoi_id": ["BRA.14"], "tree_cover_loss_ha": [10.0]}
    mcp = FakeMcp(
        {
            "run_analysis": [analysis("pending")],
            "get_analysis": [analysis("saved", result)],
        }
    )
    recorder = RecordedStatistics()
    tools = build_tools(mcp, recorder)

    command = await tools.pull_data(
        "tree_cover_loss",
        PAYLOAD,
        state={"aoi_selection": PARA_SELECTION},
        tool_call_id="call-1",
    )

    statistics = command.update["statistics"][0]
    assert statistics["id"] == "statistics-1"
    assert statistics["dataset_id"] == 4
    assert statistics["source_url"] == LINK
    assert statistics["start_date"] == "2015-01-01"
    assert statistics["end_date"] == "2024-12-31"
    assert statistics["aoi_id_to_name"] == {"BRA.14": "Pará, Brazil"}
    assert statistics["aoi_ids"] == ["BRA.14_1"]
    assert recorder.saved == [statistics]
    assert ("get_analysis", {"link": LINK}) in mcp.calls


async def test_pull_data_records_the_payload_choices_as_the_dataset():
    payload = {
        **PAYLOAD,
        "forest_filter": "primary_forest",
        "canopy_cover": 50,
    }
    mcp = FakeMcp(
        {"run_analysis": [analysis("saved", {"aoi_id": ["BRA.14"]})]}
    )
    tools = build_tools(mcp)

    command = await tools.pull_data(
        "tree_cover_loss",
        payload,
        state={"aoi_selection": PARA_SELECTION},
        tool_call_id="call-1",
    )

    dataset = command.update["dataset"]
    assert dataset["analytics_dataset"] == "tree_cover_loss"
    assert dataset["context_layer"] == "primary_forest"
    assert dataset["parameters"] == [{"name": "canopy_cover", "values": [50]}]
    statistics = command.update["statistics"][0]
    assert statistics["context_layer"] == "primary_forest"
    assert statistics["parameters"] == dataset["parameters"]


async def test_pull_data_records_the_forest_the_analysis_chose():
    ran = {
        **analysis("saved", {"aoi_id": ["BRA.14"]}),
        "metadata": {**PAYLOAD, "forest_filter": "intact_forest"},
    }
    tools = build_tools(FakeMcp({"run_analysis": [ran]}))

    command = await tools.pull_data(
        "deforestation",
        PAYLOAD,
        state={"aoi_selection": PARA_SELECTION},
        tool_call_id="call-1",
    )

    assert command.update["dataset"]["context_layer"] == "intact_forest"


async def test_pull_data_records_every_analyzed_area():
    listed = {
        "total": 2,
        "areas": [
            {"name": "Nigeria", "aoi": {"type": "admin", "ids": ["NGA"]}},
            {"name": "Ghana", "aoi": {"type": "admin", "ids": ["GHA"]}},
        ],
    }
    payload = {**PAYLOAD, "aoi": {"type": "admin", "ids": ["NGA", "GHA"]}}
    mcp = FakeMcp({"run_analysis": [analysis("saved", {"aoi_id": ["NGA"]})]})

    command = await build_tools(mcp).pull_data(
        "tree_cover_loss",
        payload,
        state={
            "aoi_selection": PARA_SELECTION,
            "messages": [ToolMessage(json.dumps(listed), tool_call_id="0")],
        },
        tool_call_id="call-1",
    )

    selection = command.update["aoi_selection"]
    assert [area["src_id"] for area in selection["aois"]] == ["NGA", "GHA"]
    assert [area["name"] for area in selection["aois"]] == ["Nigeria", "Ghana"]


async def test_list_subregions_passes_the_areas_through():
    listed = {"total": 34, "areas": []}
    mcp = FakeMcp({"list_subregions": [listed]})

    content = await build_tools(mcp).list_subregions(
        {"type": "admin", "ids": ["IDN"]}, level=1
    )

    assert json.loads(content) == listed
    assert mcp.calls == [
        (
            "list_subregions",
            {
                "aoi": {"type": "admin", "ids": ["IDN"]},
                "area_type": "admin",
                "level": 1,
                "limit": 50,
            },
        )
    ]


@pytest.mark.parametrize(
    "outcome",
    [analysis("failed"), AnalyticsMcpError("Payload is invalid")],
)
async def test_pull_data_failure_changes_nothing(outcome):
    recorder = RecordedStatistics()
    tools = build_tools(FakeMcp({"run_analysis": [outcome]}), recorder)

    command = await tools.pull_data(
        "tree_cover_loss",
        PAYLOAD,
        state={"aoi_selection": PARA_SELECTION},
        tool_call_id="call-1",
    )

    assert "statistics" not in command.update
    assert recorder.saved == []
