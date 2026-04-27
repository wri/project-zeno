import sys
import uuid
from typing import Literal, Optional
from unittest.mock import AsyncMock, patch

import pytest
import requests
from pydantic import BaseModel, Field

from src.agent.llms import SMALL_MODEL
from src.agent.state import AgentState, AOISelection
from src.agent.tools.datasets_config import DATASETS
from src.agent.tools.pick_dataset import (
    DatasetParameter,
    DatasetSelectionResult,
    pick_dataset,
)

# Use session-scoped event loop to match conftest.py fixtures and avoid
# "Event loop is closed" errors when running with other test modules
pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture(scope="function", autouse=True)
def test_db():
    """Override the global test_db fixture to avoid database connections."""
    pass


@pytest.fixture(scope="function", autouse=True)
def test_db_session():
    """Override the global test_db_session fixture to avoid database connections."""
    pass


@pytest.fixture(scope="function", autouse=True)
def test_db_pool():
    """Override the global test_db_pool fixture to avoid database pool operations."""
    pass


@pytest.fixture(scope="session", autouse=True)
def reset_google_clients():
    """Reset cached Google clients at session start to use the correct event loop."""
    # Access the actual modules via sys.modules to avoid the __init__.py re-exports
    pd_module = sys.modules["src.agent.tools.pick_dataset"]
    llms_module = sys.modules["src.agent.llms"]

    # Reset retriever cache so a fresh embeddings client is created
    pd_module.retriever_cache = None
    # Recreate SMALL_MODEL to get fresh gRPC connections on the current event loop
    llms_module.SMALL_MODEL = llms_module.get_small_model()
    yield
    # Cleanup
    pd_module.retriever_cache = None


@pytest.fixture
def state():
    return AgentState(
        aoi_selection=AOISelection(
            name="Indonesia",
            aois=[
                {
                    "source": "gadm",
                    "src_id": "IDN",
                    "subtype": "",
                    "name": "Indonesia",
                    "bbox": [94.97, -11.01, 141.02, 6.08],
                }
            ],
        )
    )


DIST_ALERT = "ecosystem disturbance alerts"
LAND_COVER_CHANGE = "land cover change"
GRASSLANDS = "grasslands"
NATURAL_LANDS = "natural lands"
TREE_COVER_LOSS = "tree cover loss"
TREE_COVER_GAIN = "tree cover gain"
CARBON_FLUX = "forest greenhouse gas net flux"
TREE_COVER = "tree cover"
TREE_COVER_LOSS_BY_DRIVER = "tree cover loss by driver"
SLUC_EF = "deforestation (sLUC) emission factors by agricultural crop"

lookup = {
    0: DIST_ALERT,
    1: LAND_COVER_CHANGE,
    2: GRASSLANDS,
    3: NATURAL_LANDS,
    4: TREE_COVER_LOSS,
    5: TREE_COVER_GAIN,
    6: CARBON_FLUX,
    7: TREE_COVER,
    8: TREE_COVER_LOSS_BY_DRIVER,
    9: SLUC_EF,
}


def _query_case_id(param):
    query = param[0].strip().replace(" ", "_")
    expected_dataset = param[1].replace(" ", "_")
    max_len = 70
    if len(query) > max_len:
        query = f"{query[:max_len]}..."
    return f"{expected_dataset}__{query}"


@pytest.fixture(
    params=[
        # Dataset 0 queries (Ecosystem disturbance alerts) - near-real-time vegetation changes
        (
            "Which year recorded more alerts within Protected Areas in Ucayali, Peru? 2023 or 2024?",
            DIST_ALERT,
        ),
        (
            "Show me recent vegetation disturbances in the Amazon basin over the past month",
            DIST_ALERT,
        ),
        (
            "Are there any significant changes to natural ecosystems in Indonesia this week?",
            DIST_ALERT,
        ),
        (
            "I need to monitor drought impacts on vegetation cover in East Africa",
            DIST_ALERT,
        ),
        (
            "What areas show signs of land management interventions in the past 6 months?",
            DIST_ALERT,
        ),
        # Dataset 1 queries (Global land cover) - annual land cover classification and change
        (
            "Which had more cropland in 2015, Nigeria or Ghana?",
            LAND_COVER_CHANGE,
        ),
        (
            "What's the trend in agricultural expansion across Southeast Asia since 2015?",
            LAND_COVER_CHANGE,
        ),
        (
            "I'm studying urbanization patterns in sub-Saharan Africa between 2020 and 2024",
            LAND_COVER_CHANGE,
        ),
        (
            "Show me areas where wetlands have been converted to other uses",
            LAND_COVER_CHANGE,
        ),
        # Dataset 2 queries (Grassland) - natural and cultivated grassland classification
        (
            "What is the total area of prairie ecosystems in North America?",
            GRASSLANDS,
        ),
        (
            "Which regions show the fastest decline in native grassland habitats?",
            GRASSLANDS,
        ),
        (
            "I need data on natural and semi-natural pastoral landscapes",
            GRASSLANDS,
        ),
        (
            "Where are the largest intact grassland ecosystems globally?",
            GRASSLANDS,
        ),
        # Dataset 3 queries (Natural lands) - SBTN baseline for conversion monitoring
        (
            "What percentage of land area in Brazil consists of natural ecosystems according to the 2020 baseline?",
            NATURAL_LANDS,
        ),
        (
            "Which provinces in Canada have the highest proportion of intact landscapes?",
            NATURAL_LANDS,
        ),
        (
            "Show me areas where natural habitats remain undisturbed by human activities",
            NATURAL_LANDS,
        ),
        (
            "What's the baseline extent of natural vegetation before any recent conversions?",
            NATURAL_LANDS,
        ),
        # Dataset 4 queries (Tree cover loss) - annual forest loss detection
        (
            "What percent of 2000 forest did Kalimantan Barat lose from 2001 through 2024?",
            TREE_COVER_LOSS,
        ),
        (
            "Which country had the most deforestation in 2018?",
            TREE_COVER_LOSS,
        ),
        (
            "I need to track forest plantations harvesting cycles in northern Europe",
            TREE_COVER_LOSS,
        ),
        (
            "Show deforestation by driver in 2019",
            TREE_COVER_LOSS,  # By driver is total, so we want this query to pick plain TCL
        ),
        # Dataset 5 queries (Tree cover gain) - cumulative forest regrowth
        (
            "Where has forest regrowth occurred in the Amazon basin between 2000 and 2020?",
            TREE_COVER_GAIN,
        ),
        (
            "Show me areas of tree cover gain in Southeast Asia over the past two decades",
            TREE_COVER_GAIN,
        ),
        (
            "Which regions show the most significant forest recovery since 2000?",
            TREE_COVER_GAIN,
        ),
        # Dataset 6 queries (Forest greenhouse gas net flux) - carbon emissions and removals
        (
            "What areas of forest are acting as net carbon sinks versus sources?",
            CARBON_FLUX,
        ),
        (
            "Show me forest carbon emissions and removals in the Congo Basin",
            CARBON_FLUX,
        ),
        (
            "Which forest regions contribute most to greenhouse gas emissions?",
            CARBON_FLUX,
        ),
        # Dataset 7 queries (Tree cover) - baseline tree canopy density
        (
            "What percentage of land area in Brazil has tree cover above 30%?",
            TREE_COVER,
        ),
        (
            "Show me areas with high tree cover density in the Pacific Northwest",
            TREE_COVER,
        ),
        (
            "Which regions have the highest tree canopy cover globally?",
            TREE_COVER,
        ),
        # Dataset 8 queries (Tree cover loss by driver) - tree cover loss by driver
        (
            "What areas of forest are experiencing the most tree cover loss due to wildfire?",
            TREE_COVER_LOSS_BY_DRIVER,
        ),
        (
            "Show me areas of tree cover loss by driver in the Congo Basin",
            TREE_COVER_LOSS_BY_DRIVER,
        ),
        (
            "Which regions show the most significant tree cover loss by driver?",
            TREE_COVER_LOSS_BY_DRIVER,
        ),
        (
            "What regions experienced the most fire-related tree cover loss?",
            TREE_COVER_LOSS_BY_DRIVER,
        ),
        # ------------------------------------------------------------------
        # Tiered selection_hints (mirrors test_pick_dataset_tiered.py)
        # Each entry is (query, expected_dataset, start_date, end_date) when
        # dates matter for the scenario; otherwise (query, expected_dataset).
        # ------------------------------------------------------------------
        (
            "What vegetation disturbances happened this month in Borneo?",
            DIST_ALERT,
            "2024-01-01",
            "2024-12-31",
        ),
        (
            "How much tree cover was lost in Brazil between 2010 and 2020?",
            TREE_COVER_LOSS,
            "2010-01-01",
            "2020-12-31",
        ),
        (
            "Why is tree cover being lost in Southeast Asia?",
            TREE_COVER_LOSS_BY_DRIVER,
            "2024-01-01",
            "2024-12-31",
        ),
        (
            "Show annual tree cover loss in Brazil from 2001 to 2024",
            TREE_COVER_LOSS,
            "2001-01-01",
            "2024-12-31",
        ),
        (
            "How much tree cover does the DRC have?",
            TREE_COVER,
            "2000-01-01",
            "2000-12-31",
        ),
        (
            "Where has foreLAND_COVER_CHANGEst regrowth occurred in Indonesia since 2000?",
            TREE_COVER_GAIN,
            "2000-01-01",
            "2020-12-31",
        ),
        (
            "What percentage of Colombia is natural land according to the 2020 SBTN baseline?",
            NATURAL_LANDS,
            "2020-01-01",
            "2020-12-31",
        ),
        (
            "How did land cover change in Brazil between 2015 and 2024?",
            LAND_COVER_CHANGE,
            "2015-01-01",
            "2024-12-31",
        ),
        (
            "How much natural grassland does Kenya have?",
            GRASSLANDS,
            "2000-01-01",
            "2022-12-31",
        ),
        (
            "How much cultivated grassland is there in Brazil?",
            LAND_COVER_CHANGE,
            "2015-01-01",
            "2024-12-31",
        ),
        (
            "Is Brazil's forest a net carbon source or sink?",
            CARBON_FLUX,
            "2001-01-01",
            "2024-12-31",
        ),
        (
            "How much tree cover was lost each year in Brazil and what were the emissions?",
            TREE_COVER_LOSS,
            "2001-01-01",
            "2024-12-31",
        ),
        (
            "What is the deforestation emission factor for soybean in Brazil?",
            SLUC_EF,
            "2024-01-01",
            "2024-12-31",
        ),
        (
            "Show recent vegetation disturbances across all ecosystems in Brazil",
            DIST_ALERT,
            "2024-01-01",
            "2024-12-31",
        ),
        (
            "What proportion of tree cover loss in Brazil is due to wildfire vs agriculture?",
            TREE_COVER_LOSS_BY_DRIVER,
            "2001-01-01",
            "2024-12-31",
        ),
        (
            "Show annual forest emissions for Brazil from 2001 to 2024",
            TREE_COVER_LOSS,
            "2001-01-01",
            "2024-12-31",
        ),
        # Tiered cases that previously asserted “not dataset X”; same rows with
        # explicit expected ID (redundant with the negative check in tiered tests).
        (
            "How much tree cover did the DRC lose between 2000 and 2020?",
            TREE_COVER_LOSS,
            "2000-01-01",
            "2020-12-31",
        ),
        (
            "Compare tree cover in 2000 vs 2020 for Brazil",
            TREE_COVER_GAIN,
            "2000-01-01",
            "2020-12-31",
        ),
        (
            "How has natural land in Colombia changed from 2015 to 2024?",
            LAND_COVER_CHANGE,
            "2015-01-01",
            "2024-12-31",
        ),
        (
            "Show the trend in natural land loss over time in Brazil",
            TREE_COVER_LOSS,
            "2015-01-01",
            "2024-12-31",
        ),
        (
            "Plot year-by-year carbon emissions from deforestation in Indonesia",
            TREE_COVER_LOSS,
            "2001-01-01",
            "2024-12-31",
        ),
    ],
    ids=_query_case_id,
)
def test_query_with_expected_dataset(request):
    p = request.param
    if len(p) == 2:
        return (p[0], p[1], "2024-01-01", "2024-12-31")
    return p


async def test_queries_return_expected_dataset(
    test_query_with_expected_dataset,
):
    query, expected_dataset, start_date, end_date = (
        test_query_with_expected_dataset
    )
    tool_call_id = str(uuid.uuid4())

    tool_call = {
        "type": "tool_call",
        "name": "pick_dataset",
        "id": tool_call_id,
        "args": {
            "query": query,
            "start_date": start_date,
            "end_date": end_date,
            "state": dict(),
            "tool_call_id": tool_call_id,
        },
    }

    command = await pick_dataset.ainvoke(tool_call)

    dataset_id = command.update.get("dataset", {}).get("dataset_id")
    assert lookup[dataset_id] == expected_dataset


@pytest.mark.parametrize(
    "query,expected_dataset_id,expected_context_layer",
    [
        ("Vegetation disturbances by natural lands", 0, "natural_lands"),
        ("Vegetation disturbances over grasslands", 0, "grasslands"),
        ("Tree cover loss by driver", 8, "driver"),
        ("Tree cover loss in primary forest", 4, "primary_forest"),
        ("Tree  cover loss in the past decade in sparse forests", 4, None),
        ("Deforestation in the past decade", 4, "primary_forest"),
        ("Deforestation in 2024", 4, "primary_forest"),
        ("Global land cover in storm seasons", 1, None),
    ],
)
async def test_query_with_context_layer(
    query, expected_dataset_id, expected_context_layer, state
):
    tool_call_id = str(uuid.uuid4())

    tool_call = {
        "type": "tool_call",
        "name": "pick_dataset",
        "id": tool_call_id,
        "args": {
            "query": query,
            "start_date": "2022-01-01",
            "end_date": "2022-12-31",
            "state": state,
            "tool_call_id": tool_call_id,
        },
    }

    command = await pick_dataset.ainvoke(tool_call)

    dataset_id = command.update.get("dataset", {}).get("dataset_id")
    assert dataset_id == expected_dataset_id
    context_layer = command.update.get("dataset", {}).get("context_layer")
    assert context_layer == expected_context_layer


@pytest.mark.parametrize(
    "query,expected_dataset_id,expected_parameter_name,expected_parameter_value",
    [
        (
            "Tree cover loss in the past decade where canopy over is greater than 50%",
            4,
            "canopy_cover",
            50,
        ),
        (
            "Tree cover loss in the past decade where canopy threshold is 23",
            4,
            "canopy_cover",
            25,
        ),
        (
            "Tree cover loss in the past decade where canopy threshold is 30",
            4,
            "canopy_cover",
            30,
        ),
        ("Tree cover loss in the past decade", 4, "canopy_cover", 30),
    ],
)
async def test_query_with_parameter(
    query,
    expected_dataset_id,
    expected_parameter_name,
    expected_parameter_value,
):
    tool_call_id = str(uuid.uuid4())

    tool_call = {
        "type": "tool_call",
        "name": "pick_dataset",
        "id": tool_call_id,
        "args": {
            "query": query,
            "start_date": "2022-01-01",
            "end_date": "2022-12-31",
            "state": dict(),
            "tool_call_id": tool_call_id,
        },
    }

    command = await pick_dataset.ainvoke(tool_call)

    dataset_id = command.update.get("dataset", {}).get("dataset_id")
    assert dataset_id == expected_dataset_id

    if expected_parameter_name is None:
        assert command.update.get("dataset", {}).get("parameters") is None
    else:
        param = command.update.get("dataset", {}).get("parameters")[0]
        assert param["name"] == expected_parameter_name
        assert expected_parameter_value in param["values"]


@pytest.mark.parametrize(
    "dataset",
    [
        DIST_ALERT,
        LAND_COVER_CHANGE,
        GRASSLANDS,
        NATURAL_LANDS,
        TREE_COVER,
        TREE_COVER_LOSS,
        TREE_COVER_GAIN,
        CARBON_FLUX,
    ],
)
async def test_tile_url_contains_date(dataset, state):
    year = "2020"
    if dataset == TREE_COVER:
        year = "2000"
    tool_call_id = str(uuid.uuid4())

    tool_call = {
        "type": "tool_call",
        "name": "pick_dataset",
        "id": tool_call_id,
        "args": {
            "query": f"Find me {dataset} data for {year}",
            "start_date": f"{year}-01-01",
            "end_date": f"{year}-12-31",
            "state": state,
            "tool_call_id": tool_call_id,
        },
    }

    command = await pick_dataset.ainvoke(tool_call)

    tile_url = command.update.get("dataset", {}).get("tile_url")
    if dataset not in [NATURAL_LANDS, TREE_COVER_GAIN, CARBON_FLUX]:
        assert year in tile_url
    tile_url_format = tile_url.format(z=3, x=5, y=3)
    if "eoapi.globalnaturewatch.org" in tile_url_format:
        tile_url_format = tile_url_format.replace(
            "eoapi.globalnaturewatch.org", "eoapi-cache.globalnaturewatch.org"
        )
    response = requests.get(tile_url_format)
    assert response.status_code == 200


async def test_tile_url_contains_default_dates(state):
    tool_call_id = str(uuid.uuid4())

    tool_call = {
        "type": "tool_call",
        "name": "pick_dataset",
        "id": tool_call_id,
        "args": {
            "query": "Find me tree cover loss data",
            "start_date": None,
            "end_date": None,
            "state": state,
            "tool_call_id": tool_call_id,
        },
    }

    command = await pick_dataset.ainvoke(tool_call)

    tile_url = command.update.get("dataset", {}).get("tile_url")
    assert "start_year=2001" in tile_url


async def test_tree_cover_tile_url_with_canopy_density(state):
    tool_call_id = str(uuid.uuid4())

    tool_call = {
        "type": "tool_call",
        "name": "pick_dataset",
        "id": tool_call_id,
        "args": {
            "query": "Tree cover where where canopy density is greater than 15%",
            "start_date": "2000-01-01",
            "end_date": "2000-12-31",
            "state": state,
            "tool_call_id": tool_call_id,
        },
    }

    command = await pick_dataset.ainvoke(tool_call)

    tile_url = command.update.get("dataset", {}).get("tile_url")
    assert "tcd_15" in tile_url
    tile_url_format = tile_url.format(z=3, x=5, y=3)
    response = requests.get(tile_url_format)
    assert response.status_code == 200


def _make_fake_selection(
    dataset_id: int,
    context_layer: str | None,
    parameters: Optional[list[DatasetParameter]] = None,
) -> DatasetSelectionResult:
    """Build a DatasetSelectionResult for the given dataset with a fake context_layer."""
    ds = next(d for d in DATASETS if d["dataset_id"] == dataset_id)
    return DatasetSelectionResult(
        dataset_id=dataset_id,
        dataset_name=ds["dataset_name"],
        context_layer=context_layer,
        reason="test",
        tile_url=ds["tile_url"],
        analytics_api_endpoint=ds.get("analytics_api_endpoint", ""),
        description=ds["description"],
        prompt_instructions=ds.get("prompt_instructions", ""),
        methodology=ds.get("methodology", ""),
        cautions=ds.get("cautions", ""),
        function_usage_notes=ds.get("function_usage_notes", ""),
        citation=ds.get("citation", ""),
        content_date=ds.get("content_date", ""),
        parameters=parameters,
    )


@pytest.mark.parametrize(
    "dataset_id,hallucinated_layer",
    [
        (4, "Tree cover loss"),  # The exact bug from the trace
        (1, "Global land cover"),
        (7, "tree cover"),
    ],
)
async def test_hallucinated_context_layer_is_discarded(
    dataset_id,
    hallucinated_layer,
):
    """Verify that invalid context_layer values from LLM are set to None."""
    import pandas as pd

    fake_selection = _make_fake_selection(dataset_id, hallucinated_layer)
    candidate_df = pd.DataFrame(
        [d for d in DATASETS if d["dataset_id"] == dataset_id]
    )
    tool_call_id = str(uuid.uuid4())

    with (
        patch(
            "src.agent.tools.pick_dataset.rag_candidate_datasets",
            new_callable=AsyncMock,
            return_value=candidate_df,
        ),
        patch(
            "src.agent.tools.pick_dataset.select_best_dataset",
            new_callable=AsyncMock,
            return_value=fake_selection,
        ),
    ):
        tool_call = {
            "type": "tool_call",
            "name": "pick_dataset",
            "id": tool_call_id,
            "args": {
                "query": "test query",
                "start_date": "2022-01-01",
                "end_date": "2022-12-31",
                "state": dict(),
                "tool_call_id": tool_call_id,
            },
        }

        command = await pick_dataset.ainvoke(tool_call)

    result_layer = command.update.get("dataset", {}).get("context_layer")
    assert result_layer is None, (
        f"Expected hallucinated layer '{hallucinated_layer}' to be discarded, "
        f"but got '{result_layer}'"
    )


@pytest.mark.parametrize(
    "dataset_id,hallucinated_parameter",
    [
        (4, [{"name": "canopy_cover", "values": [-1], "description": ""}]),
        (7, [{"name": "made_up", "values": [30], "description": ""}]),
    ],
)
async def test_hallucinated_parameter_is_discarded(
    dataset_id,
    hallucinated_parameter,
):
    """Verify that invalid parameter values from LLM are set to None."""
    import pandas as pd

    fake_selection = _make_fake_selection(
        dataset_id, None, parameters=hallucinated_parameter
    )
    candidate_df = pd.DataFrame(
        [d for d in DATASETS if d["dataset_id"] == dataset_id]
    )
    tool_call_id = str(uuid.uuid4())

    with (
        patch(
            "src.agent.tools.pick_dataset.rag_candidate_datasets",
            new_callable=AsyncMock,
            return_value=candidate_df,
        ),
        patch(
            "src.agent.tools.pick_dataset.select_best_dataset",
            new_callable=AsyncMock,
            return_value=fake_selection,
        ),
    ):
        tool_call = {
            "type": "tool_call",
            "name": "pick_dataset",
            "id": tool_call_id,
            "args": {
                "query": "test query",
                "start_date": "2022-01-01",
                "end_date": "2022-12-31",
                "state": dict(),
                "tool_call_id": tool_call_id,
            },
        }

        command = await pick_dataset.ainvoke(tool_call)

    result_params = command.update.get("dataset", {}).get("parameters")
    assert not result_params, (
        f"Expected hallucinated paramter '{hallucinated_parameter}' to be discarded, "
        f"but got '{result_params}'"
    )


async def test_valid_context_layer_is_preserved():
    """Verify that a valid context_layer (e.g. 'driver' for DIST-ALERT) is kept."""
    import pandas as pd

    fake_selection = _make_fake_selection(0, "driver")
    candidate_df = pd.DataFrame([d for d in DATASETS if d["dataset_id"] == 0])
    tool_call_id = str(uuid.uuid4())

    with (
        patch(
            "src.agent.tools.pick_dataset.rag_candidate_datasets",
            new_callable=AsyncMock,
            return_value=candidate_df,
        ),
        patch(
            "src.agent.tools.pick_dataset.select_best_dataset",
            new_callable=AsyncMock,
            return_value=fake_selection,
        ),
    ):
        tool_call = {
            "type": "tool_call",
            "name": "pick_dataset",
            "id": tool_call_id,
            "args": {
                "query": "disturbance alerts by driver",
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
                "state": dict(),
                "tool_call_id": tool_call_id,
            },
        }

        command = await pick_dataset.ainvoke(tool_call)

    result_layer = command.update.get("dataset", {}).get("context_layer")
    assert result_layer == "driver"


async def test_tcl_by_driver_always_gets_driver_context_layer(state):
    """Dataset 8 (TCL by driver) should always have context_layer='driver',
    even if the LLM returns None."""
    import pandas as pd

    fake_selection = _make_fake_selection(
        8, None
    )  # LLM returns no context_layer
    candidate_df = pd.DataFrame([d for d in DATASETS if d["dataset_id"] == 8])
    tool_call_id = str(uuid.uuid4())

    with (
        patch(
            "src.agent.tools.pick_dataset.rag_candidate_datasets",
            new_callable=AsyncMock,
            return_value=candidate_df,
        ),
        patch(
            "src.agent.tools.pick_dataset.select_best_dataset",
            new_callable=AsyncMock,
            return_value=fake_selection,
        ),
    ):
        tool_call = {
            "type": "tool_call",
            "name": "pick_dataset",
            "id": tool_call_id,
            "args": {
                "query": "tree cover loss by driver",
                "start_date": "2022-01-01",
                "end_date": "2022-12-31",
                "state": state,
                "tool_call_id": tool_call_id,
            },
        }

        command = await pick_dataset.ainvoke(tool_call)

    result_layer = command.update.get("dataset", {}).get("context_layer")
    assert result_layer == "driver"


async def test_queries_context_layer_outside_extent():
    """
    Test a tropics only-contextual layer isn't selected
    """

    query = "Tree cover loss in primary forest"
    expected_dataset_id = 4
    expected_context_layer = None
    tool_call_id = str(uuid.uuid4())
    non_tropics_state = AgentState(
        aoi_selection=AOISelection(
            name="Canada",
            aois=[
                {
                    "source": "gadm",
                    "src_id": "CAN",
                    "subtype": "",
                    "name": "Canada",
                    "bbox": [-141.0, 41.68, -52.62, 83.11],
                }
            ],
        )
    )

    tool_call = {
        "type": "tool_call",
        "name": "pick_dataset",
        "id": tool_call_id,
        "args": {
            "query": query,
            "start_date": "2022-01-01",
            "end_date": "2022-12-31",
            "state": non_tropics_state,
            "tool_call_id": tool_call_id,
        },
    }

    command = await pick_dataset.ainvoke(tool_call)

    dataset_id = command.update.get("dataset", {}).get("dataset_id")
    assert dataset_id == expected_dataset_id
    context_layer = command.update.get("dataset", {}).get("context_layer")
    assert context_layer == expected_context_layer


async def test_queries_context_layer_extent_definition():
    """
    Test a a tropics-only layer is chosen inside the extent using our extent definition,
    not the LLM's inherent knowledge. Using Chad with primary forest as an example:
    there is primary forest extent in the very south of Chad, but LLM sometimes
    uses world knowledge about ecology or its own extents to contradit ours.
    """

    query = "Tree cover loss in primary forest"
    expected_dataset_id = 4
    expected_context_layer = "primary_forest"
    tool_call_id = str(uuid.uuid4())
    non_tropics_state = AgentState(
        aoi_selection=AOISelection(
            name="Chad",
            aois=[
                {
                    "source": "gadm",
                    "src_id": "TCD",
                    "subtype": "",
                    "name": "Chad",
                    "bbox": [13.47, 7.44, 24.00, 23.45],
                }
            ],
        )
    )

    tool_call = {
        "type": "tool_call",
        "name": "pick_dataset",
        "id": tool_call_id,
        "args": {
            "query": query,
            "start_date": "2022-01-01",
            "end_date": "2022-12-31",
            "state": non_tropics_state,
            "tool_call_id": tool_call_id,
        },
    }

    command = await pick_dataset.ainvoke(tool_call)

    dataset_id = command.update.get("dataset", {}).get("dataset_id")
    assert dataset_id == expected_dataset_id
    context_layer = command.update.get("dataset", {}).get("context_layer")
    assert context_layer == expected_context_layer


class LanguageJudgeResult(BaseModel):
    language: Literal["spanish", "portuguese", "english"] = Field(
        description="Detected language for the provided text."
    )


async def _judge_language_with_llm(text: str) -> str:
    """Use the project small model as an LLM judge for language detection."""
    prompt = (
        "Classify the language of the following text as exactly one of: "
        "spanish, portuguese, english.\n"
        f"Text: {text}"
    )
    chain = SMALL_MODEL.with_structured_output(LanguageJudgeResult)
    result = await chain.ainvoke(prompt)
    return result.language


@pytest.mark.parametrize(
    "query,expected_language",
    [
        (
            "Que tamaño de area fue desforestada en los Estados Unidos entre 2015 y 2020?",
            "spanish",
        ),
        (
            "Qual a extensão de terras cultiváveis ​​na República da Irlanda?",
            "portuguese",
        ),
        (
            "What are the trends in grassland area in Spain",
            "english",
        ),
    ],
)
async def test_pick_dataset_reason_matches_query_language_with_llm_judge(
    query,
    expected_language,
    state,
):
    tool_call_id = str(uuid.uuid4())
    tool_call = {
        "type": "tool_call",
        "name": "pick_dataset",
        "id": tool_call_id,
        "args": {
            "query": query,
            "start_date": "2015-01-01",
            "end_date": "2020-12-31",
            "state": state,
            "tool_call_id": tool_call_id,
        },
    }

    command = await pick_dataset.ainvoke(tool_call)
    reason = command.update.get("dataset", {}).get("reason", "")
    judged_language = await _judge_language_with_llm(reason)

    assert judged_language == expected_language, (
        f"Expected reason language '{expected_language}', "
        f"but judge returned '{judged_language}'. Reason: {reason}"
    )
