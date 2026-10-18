"""curated_charts and get_chart_code: GNW's own chart generators over MCP.

The pull is stubbed as in test_tools; the generators run for real.
"""

import pytest
from fastmcp import Client

import src.mcp.charts as charts
import src.mcp.data as data
from src.agent.datasets.handlers.base import DataPullResult
from src.mcp.server import mcp_server

PARA = {
    "source": "gadm",
    "src_id": "BRA.14_1",
    "name": "Pará, Brazil",
    "subtype": "state-province",
    "bbox": [-58.9, -9.8, -46.0, 2.6],
}
SOURCE_URL = (
    "http://analytics.globalnaturewatch.org/v0/land_change/"
    "tree_cover_loss/analytics/ab485026"
)


async def _call(tool: str, args: dict):
    async with Client(mcp_server) as client:
        return await client.call_tool(tool, args, raise_on_error=False)


@pytest.fixture
def pull_returns(monkeypatch):
    """Stub the area lookup; the analytics handler returns the columns
    the test sets, and records its calls."""
    returned: dict = {"data": {}, "calls": []}

    async def fake_lookup(aoi_ids):
        return [dict(PARA)]

    async def fake_pull(self, **kwargs):
        returned["calls"].append(kwargs)
        return DataPullResult(
            success=True,
            data=returned["data"],
            message="ok",
            data_points_count=1,
            analytics_api_url=SOURCE_URL,
        )

    monkeypatch.setattr(data, "lookup_areas", fake_lookup)
    monkeypatch.setattr(data.AnalyticsHandler, "pull_data", fake_pull)
    return returned


async def test_tree_cover_loss_charts_come_with_provenance(pull_returns):
    pull_returns["data"] = {
        "aoi_id": ["BRA.14", "BRA.14"],
        "aoi_type": ["admin", "admin"],
        "tree_cover_loss_year": [2021, 2020],
        "area_ha": [693512.76, 805620.12],
        "carbon_emissions_MgCO2e": [4.6e8, 4.9e8],
        "name": ["Pará", "Pará"],
    }
    result = await _call(
        "curated_charts",
        {"aoi_ids": ["gadm:BRA.14_1"], "dataset_id": 4, "canopy_cover": 30},
    )

    structured = result.structured_content
    assert structured["curated"] is True
    assert structured["result_id"] == "ab485026"
    assert structured["canopy_cover"] == 30
    assert structured["areas"] == [
        {"aoi_id": "gadm:BRA.14_1", "name": "Pará, Brazil"}
    ]
    assert structured["generator"]["name"] == "TCLChartGenerator"
    assert structured["generator"]["code_url"].endswith(
        "src/api/services/charts/tcl.py"
    )
    loss, emissions = structured["charts"]
    # Localised titles, rows sorted by year, the catalog's series color.
    assert loss["title"] == "Annual Tree Cover Loss"
    assert [row["tree_cover_loss_year"] for row in loss["chart_data"]] == [
        2020,
        2021,
    ]
    assert loss["series_color"] == "#DC6C9A"
    assert emissions["y_axis"] == "carbon_emissions_MgCO2e"

    text = result.content[0].text
    assert "tree_cover_loss_year,area_ha,carbon_emissions_MgCO2e,name" in text
    assert "aoi_type" not in text
    # The second chart draws the same rows, so they are not repeated.
    assert "The rows of chart 1." in text
    assert "Citation: Hansen et al., 2013" in text


async def test_categories_get_the_catalog_colors(pull_returns):
    pull_returns["data"] = {
        "tree_cover_loss_driver": [
            "Wildfire",
            "Permanent agriculture",
            "Settlements and infrastructure",
        ],
        "area_ha": [3.0e6, 1.5e7, 2.8e4],
        "carbon_emissions_MgCO2e": [8.8e8, 9.5e9, 1.5e7],
        "name": ["Pará"] * 3,
    }
    result = await _call(
        "curated_charts", {"aoi_ids": ["gadm:BRA.14_1"], "dataset_id": 8}
    )
    (pie,) = result.structured_content["charts"]
    # The API's label matches the catalog's "Settlements & Infrastructure".
    assert pie["color_map"] == {
        "Permanent agriculture": "#E39D29",
        "Wildfire": "#885128",
        "Settlements and infrastructure": "#A354A0",
    }


async def test_a_dataset_without_curated_charts_is_refused(
    monkeypatch, pull_returns
):
    monkeypatch.setattr(
        charts,
        "DETERMINISTIC_GENERATORS",
        [g for g in charts.DETERMINISTIC_GENERATORS if g.dataset_id != 7],
    )
    result = await _call(
        "curated_charts", {"aoi_ids": ["gadm:BRA.14_1"], "dataset_id": 7}
    )
    assert result.is_error
    assert "no curated charts" in result.content[0].text
    assert pull_returns["calls"] == []


@pytest.mark.parametrize("dataset_id", [12, 999])
async def test_hidden_and_unknown_datasets_are_refused(dataset_id):
    for tool in ("curated_charts", "get_chart_code"):
        args = {"dataset_id": dataset_id}
        if tool == "curated_charts":
            args["aoi_ids"] = ["gadm:BRA.14_1"]
        result = await _call(tool, args)
        assert result.is_error
        assert f"No dataset {dataset_id}" in result.content[0].text


async def test_curated_only_chart_data_is_withheld(monkeypatch, pull_returns):
    monkeypatch.setattr(charts, "is_curated_only", lambda dataset_id: True)
    pull_returns["data"] = {
        "tree_cover_loss_year": [2020],
        "area_ha": [805620.12],
        "carbon_emissions_MgCO2e": [4.9e8],
    }
    result = await _call(
        "curated_charts", {"aoi_ids": ["gadm:BRA.14_1"], "dataset_id": 4}
    )
    assert all(
        chart["chart_data"] == []
        for chart in result.structured_content["charts"]
    )
    assert "805620.12" not in result.content[0].text


async def test_get_chart_code_returns_the_generator_source():
    result = await _call("get_chart_code", {"dataset_id": 4})
    assert (
        "class TCLChartGenerator(ChartGenerator)"
        in (result.structured_content["source"])
    )
    assert result.structured_content["path"] == (
        "src/api/services/charts/tcl.py"
    )


async def test_the_code_is_also_a_resource():
    async with Client(mcp_server) as client:
        contents = await client.read_resource("gnw://charts/8/code")
    assert "class TCLByDriverChartGenerator" in contents[0].text
