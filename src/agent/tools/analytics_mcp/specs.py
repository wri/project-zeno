"""The analytics MCP tools as agent tool specs, wired to the analytics API's
MCP server and Zeno's dataset catalog."""

import asyncio
import os

from langchain_core.tools import StructuredTool

from src.agent.datasets.config import DATASETS
from src.agent.datasets.handlers.analytics_handler import (
    DEFAULT_CANOPY_COVER,
    LAND_COVER_CHANGE_ID,
    NATURAL_FOREST_DEFAULT_CANOPY_COVER,
    TREE_COVER_LOSS_BY_DRIVER_ID,
    TREE_COVER_LOSS_BY_FIRES_ID,
    analytics_api_headers,
)
from src.agent.tool_spec import ToolCategory, ToolSpec
from src.agent.tools.analytics_mcp.catalog_datasets import CatalogDatasets
from src.agent.tools.analytics_mcp.client import StreamableHttpAnalyticsMcp
from src.agent.tools.analytics_mcp.dataset_ids import DatasetIds
from src.agent.tools.analytics_mcp.payload_choices import PayloadChoices
from src.agent.tools.analytics_mcp.tools import AnalyticsMcpTools
from src.agent.tools.pull_data import record_statistics

POLL_TIMEOUT_SECONDS = 180


def analytics_mcp_url() -> str:
    base_url = os.getenv(
        "ANALYTICS_API_BASE_URL", "https://analytics.globalnaturewatch.org"
    )
    return os.getenv("ANALYTICS_MCP_URL", base_url.rstrip("/") + "/mcp/")


def authorization_headers() -> dict[str, str]:
    """The analytics API credentials. The MCP client sets its own content
    headers."""
    headers = analytics_api_headers()
    return {
        "Authorization": headers["Authorization"],
        "X-environment": headers["X-environment"],
    }


tools = AnalyticsMcpTools(
    mcp=StreamableHttpAnalyticsMcp(analytics_mcp_url(), authorization_headers),
    dataset_ids=DatasetIds(
        catalog=DATASETS,
        intersection_ids={
            ("tree_cover_loss", "driver"): TREE_COVER_LOSS_BY_DRIVER_ID,
            ("tree_cover_loss", "fire"): TREE_COVER_LOSS_BY_FIRES_ID,
        },
        alias_ids={"land_cover_composition": LAND_COVER_CHANGE_ID},
    ),
    datasets=CatalogDatasets(DATASETS),
    payload_choices=PayloadChoices(
        default_canopy_cover=DEFAULT_CANOPY_COVER,
        natural_forest_canopy_cover=NATURAL_FOREST_DEFAULT_CANOPY_COVER,
    ),
    record_statistics=record_statistics,
    sleep=asyncio.sleep,
    poll_timeout_seconds=POLL_TIMEOUT_SECONDS,
)

PICK_AOI_SPEC = ToolSpec(
    tool=StructuredTool.from_function(
        coroutine=tools.pick_aoi, name="pick_aoi"
    ),
    category=ToolCategory.PRIMITIVE,
    prompt_fragment=(
        "- pick_aoi(places): find and select the areas to analyze; pass every "
        "place the question names in one call. Give each place's full name, "
        "every word of it; put the country or region it is in after a comma "
        "and the kind of area in area_types, not in the name."
    ),
)
LIST_DATASETS_SPEC = ToolSpec(
    tool=StructuredTool.from_function(
        coroutine=tools.list_datasets, name="list_datasets"
    ),
    category=ToolCategory.PRIMITIVE,
    prompt_fragment=(
        "- list_datasets(): the datasets that can be analyzed. To answer "
        "with data: pick_aoi, list_datasets, pick_dataset, pull_data, then "
        "generate_insights."
    ),
)
LIST_SUBREGIONS_SPEC = ToolSpec(
    tool=StructuredTool.from_function(
        coroutine=tools.list_subregions, name="list_subregions"
    ),
    category=ToolCategory.PRIMITIVE,
    prompt_fragment=(
        "- list_subregions(aoi): the regions, states, counties or protected "
        "areas within an area, or the countries of the world (WLD), to pull "
        "together for questions comparing the parts of a place."
    ),
)
PICK_DATASET_SPEC = ToolSpec(
    tool=StructuredTool.from_function(
        coroutine=tools.pick_dataset, name="pick_dataset"
    ),
    category=ToolCategory.PRIMITIVE,
    prompt_fragment=(
        "- pick_dataset(dataset): select a dataset from list_datasets and "
        "get its payload schema."
    ),
)
PULL_DATA_SPEC = ToolSpec(
    tool=StructuredTool.from_function(
        coroutine=tools.pull_data, name="pull_data"
    ),
    category=ToolCategory.PRIMITIVE,
    prompt_fragment=(
        "- pull_data(dataset, payload): run the analysis, with a payload "
        "matching pick_dataset's schema and the aoi from pick_aoi. Use exactly "
        "the period asked for (through 2024 means an end of 2024). Then call "
        "generate_insights with the question restated with the areas and "
        "period analyzed; for amounts or trends, ask it for the total over "
        "the period too."
    ),
)
