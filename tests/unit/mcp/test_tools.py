"""The MCP tools, called through an in-process FastMCP client.

The database and the analytics API are stubbed: these tests pin what each
tool sends to zeno's own code and what it returns to a model.
"""

import pandas as pd
import pytest
from fastmcp import Client

import src.mcp.areas as areas
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


async def _call(tool: str, args: dict):
    async with Client(mcp_server) as client:
        return await client.call_tool(tool, args, raise_on_error=False)


# --- the server ----------------------------------------------------------


async def test_server_offers_the_read_only_tools():
    async with Client(mcp_server) as client:
        tools = await client.list_tools()
    assert [tool.name for tool in tools] == [
        "resolve_areas",
        "search_areas",
        "list_datasets",
        "get_dataset",
        "pull_data",
    ]
    assert all(tool.annotations.read_only_hint for tool in tools)


# --- datasets ------------------------------------------------------------


async def test_list_datasets_hides_lgms_and_describes_every_dataset():
    result = await _call("list_datasets", {})
    datasets = result.structured_content["datasets"]
    assert 12 not in [ds["dataset_id"] for ds in datasets]
    assert "LGMS" not in result.content[0].text
    assert all(ds["card"] for ds in datasets)


async def test_get_dataset_gives_the_options_pull_data_accepts():
    result = await _call("get_dataset", {"dataset_id": 4})
    details = result.structured_content
    assert [layer["value"] for layer in details["context_layers"]] == [
        "primary_forest",
        "intact_forest",
        "natural_forest",
    ]
    assert details["parameters"][0]["name"] == "canopy_cover"
    assert details["citation"].startswith("Hansen et al., 2013")
    assert details["colors"]["series_color"]


@pytest.mark.parametrize("dataset_id", [12, 999])
async def test_get_dataset_refuses_hidden_and_unknown_ids(dataset_id):
    result = await _call("get_dataset", {"dataset_id": dataset_id})
    assert result.is_error
    assert f"No dataset {dataset_id}" in result.content[0].text


# --- areas ---------------------------------------------------------------


async def test_search_areas_searches_without_a_user_or_custom_areas(
    monkeypatch,
):
    calls = []

    async def fake_search(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame(
            [
                {**PARA, "corrected": False, "similarity_score": 0.9},
                {
                    **PARA,
                    "src_id": "BRA.14.1_1",
                    "name": "Paraná, Brazil",
                    "corrected": True,
                },
            ]
        )

    monkeypatch.setattr(areas, "search_aois", fake_search)
    result = await _call("search_areas", {"name": "Para, Brazil"})

    assert calls[0]["user_id"] is None
    assert calls[0]["include_custom"] is False
    found = result.structured_content["areas"]
    assert [area["aoi_id"] for area in found] == [
        "gadm:BRA.14_1",
        "gadm:BRA.14.1_1",
    ]
    text = result.content[0].text
    assert "gadm:BRA.14_1: Pará, Brazil (state-province)" in text
    assert "Paraná, Brazil (state-province) — spelling corrected" in text


async def test_search_areas_refuses_a_custom_source():
    result = await _call(
        "search_areas", {"name": "my area", "sources": ["custom"]}
    )
    assert result.is_error


@pytest.mark.parametrize(
    ("aoi_id", "message"),
    [
        ("custom:b89bcc67", "Custom areas are not available"),
        ("BRA.14_1", "is not an area id"),
        ("nowhere:1", "unknown source"),
    ],
)
async def test_lookup_refuses_bad_ids_before_any_query(aoi_id, message):
    result = await _call("pull_data", {"aoi_ids": [aoi_id], "dataset_id": 4})
    assert result.is_error
    assert message in result.content[0].text


# --- pull_data -------------------------------------------------------------


@pytest.fixture
def pulled(monkeypatch):
    """Stub the area lookup and the analytics handler; record the call."""
    calls = []

    async def fake_lookup(aoi_ids):
        return [dict(PARA)]

    async def fake_pull(self, **kwargs):
        calls.append(kwargs)
        # The real handler strips the GADM version suffix in place.
        for aoi in kwargs["aois"]:
            aoi["src_id"] = aoi["src_id"][:-2]
        return DataPullResult(
            success=True,
            data={
                "aoi_id": ["BRA.14", "BRA.14"],
                "aoi_type": ["admin", "admin"],
                "tree_cover_loss_year": [2021, 2020],
                "area_ha": [693512.76, 805620.12],
                "name": ["Pará", "Pará"],
            },
            message="ok",
            data_points_count=2,
            analytics_api_url=(
                "http://analytics.globalnaturewatch.org/v0/land_change/"
                "tree_cover_loss/analytics/df747c81"
            ),
        )

    monkeypatch.setattr(data, "lookup_areas", fake_lookup)
    monkeypatch.setattr(data.AnalyticsHandler, "pull_data", fake_pull)
    return calls


async def test_pull_data_sends_the_agents_dataset_fields(pulled):
    await _call(
        "pull_data",
        {
            "aoi_ids": ["gadm:BRA.14_1"],
            "dataset_id": 4,
            "start_date": "2020-01-01",
            "end_date": "2021-12-31",
            "context_layer": "primary_forest",
            "canopy_cover": 50,
        },
    )
    call = pulled[0]
    assert call["dataset"] == {
        "dataset_id": 4,
        "dataset_name": "Tree cover loss",
        "context_layer": "primary_forest",
        "parameters": [{"name": "canopy_cover", "values": [50]}],
    }
    assert (call["start_date"], call["end_date"]) == (
        "2020-01-01",
        "2021-12-31",
    )
    assert call["change_over_time_query"] is False


async def test_pull_data_returns_the_numbers_in_its_text(pulled):
    result = await _call(
        "pull_data",
        {"aoi_ids": ["gadm:BRA.14_1"], "dataset_id": 4, "start_date": "2020"},
    )
    assert result.is_error  # not a date
    result = await _call(
        "pull_data",
        {
            "aoi_ids": ["gadm:BRA.14_1"],
            "dataset_id": 4,
            "start_date": "2020-01-01",
            "end_date": "2021-12-31",
        },
    )
    text = result.content[0].text
    # Sorted by year, as CSV, without the meta columns.
    assert (
        "tree_cover_loss_year,area_ha,name\n"
        "2020,805620.12,Pará\n"
        "2021,693512.76,Pará"
    ) in text
    assert "Citation: Hansen et al., 2013" in text

    structured = result.structured_content
    assert structured["result_id"] == "df747c81"
    assert structured["row_count"] == 2
    # The echoed id is the one the caller sent, not the handler's copy.
    assert structured["areas"] == [
        {"aoi_id": "gadm:BRA.14_1", "name": "Pará, Brazil"}
    ]


async def test_pull_data_tells_the_model_when_dates_were_fitted(pulled):
    result = await _call(
        "pull_data",
        {
            "aoi_ids": ["gadm:BRA.14_1"],
            "dataset_id": 4,
            "start_date": "1990-01-01",
            "end_date": "2021-12-31",
        },
    )
    assert pulled[0]["start_date"] == "2001-01-01"
    assert result.structured_content["date_range_clamped"] is True
    assert "fitted to the dataset's coverage" in result.content[0].text


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ({"dataset_id": 12}, "No dataset 12"),
        ({"dataset_id": 4, "context_layer": "mangroves"}, "no context layer"),
        ({"dataset_id": 4, "canopy_cover": 42}, "canopy_cover must be one of"),
        ({"dataset_id": 11, "canopy_cover": 30}, "no canopy_cover parameter"),
        (
            {
                "dataset_id": 4,
                "start_date": "1990-01-01",
                "end_date": "1995-12-31",
            },
            "outside the available range",
        ),
    ],
)
async def test_pull_data_refuses_before_calling_the_api(pulled, args, message):
    result = await _call("pull_data", {"aoi_ids": ["gadm:BRA.14_1"], **args})
    assert result.is_error
    assert message in result.content[0].text
    assert pulled == []


async def test_pull_data_reports_a_failed_pull(monkeypatch, pulled):
    async def failing_pull(self, **kwargs):
        return DataPullResult(success=False, data=None, message="API down")

    monkeypatch.setattr(data.AnalyticsHandler, "pull_data", failing_pull)
    result = await _call(
        "pull_data", {"aoi_ids": ["gadm:BRA.14_1"], "dataset_id": 4}
    )
    assert result.is_error
    assert "No data found" in result.content[0].text
    assert "API down" in result.content[0].text


async def test_pull_data_withholds_curated_only_rows(monkeypatch, pulled):
    monkeypatch.setattr(data, "is_curated_only", lambda dataset_id: True)
    result = await _call(
        "pull_data", {"aoi_ids": ["gadm:BRA.14_1"], "dataset_id": 4}
    )
    assert result.structured_content["rows"] == []
    assert "805620.12" not in result.content[0].text


async def test_pull_data_refuses_areas_from_two_sources(monkeypatch, pulled):
    async def mixed_lookup(aoi_ids):
        return [dict(PARA), {**PARA, "source": "kba", "src_id": "19363"}]

    monkeypatch.setattr(data, "lookup_areas", mixed_lookup)
    result = await _call(
        "pull_data",
        {"aoi_ids": ["gadm:BRA.14_1", "kba:19363"], "dataset_id": 4},
    )
    assert result.is_error
    assert "multiple sources" in result.content[0].text
    assert pulled == []


async def test_lookup_areas_keeps_a_repeated_id_once(monkeypatch):
    # The analytics API rejects a request whose feature ids repeat.
    sent = {}

    class _Result:
        def mappings(self):
            return self

        def all(self):
            return [PARA]

    class _Conn:
        async def execute(self, query, params):
            sent.update(params)
            return _Result()

    class _Pool:
        async def __aenter__(self):
            return _Conn()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(areas, "get_connection_from_pool", _Pool)

    found = await areas.lookup_areas(
        ["gadm:BRA.14_1", " gadm:BRA.14_1", "gadm:BRA.14_1"]
    )

    assert sent["ids"] == ["BRA.14_1"]
    assert [a["src_id"] for a in found] == ["BRA.14_1"]
