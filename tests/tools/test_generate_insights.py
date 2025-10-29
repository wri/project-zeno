import asyncio
import uuid

import pytest

from src.tools.generate_insights import generate_insights

# Force sequential execution to avoid race conditions with shared sandbox container
# Mark as sandbox tests requiring Docker
pytestmark = [pytest.mark.serial, pytest.mark.sandbox, pytest.mark.asyncio]


@pytest.fixture(scope="function", autouse=True)
def test_db():
    """Override the global test_db fixture to avoid database connections."""
    pass


@pytest.fixture(scope="function", autouse=True)
def test_db_session():
    """Override the global test_db_session fixture to avoid database connections."""
    pass


@pytest.fixture(scope="module")
def event_loop():
    """Create a single event loop for all tests in this module."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    # Don't close the loop immediately - let pytest-asyncio handle it
    try:
        loop.close()
    except:
        pass


@pytest.mark.asyncio
async def test_generate_insights_comparison():
    update = {
        "aoi": {
            "source": "gadm",
            "src_id": "USA.3.11",
            "name": "Pima, Arizona, United States",
            "subtype": "district-county",
            "gadm_id": "USA.3.11_1",
        },
        "subregion_aois": None,
        "subregion": None,
        "aoi_name": "Pima, Arizona, United States",
        "subtype": "district-county",
        "dataset": {
            "dataset_id": 4,
            "context_layer": None,
            "date_request_match": True,
            "reason": "The Tree cover loss dataset is specifically designed to map annual global forest loss and monitor deforestation trends from 2001 to 2024, making it the perfect match for analyzing tree cover loss trends over time.",
            "tile_url": "https://tiles.globalforestwatch.org/umd_tree_cover_loss/latest/dynamic/{z}/{x}/{y}.png?start_year=2001&end_year=2024&tree_cover_density_threshold=25&render_type=true_color",
            "dataset_name": "Tree cover loss",
            "analytics_api_endpoint": "/v0/land_change/tree_cover_loss/analytics",
            "description": "Tree Cover Loss (Hansen/UMD/GLAD) maps annual global forest loss from 2001 to 2024 at 30",
            "prompt_instructions": "Reports gross annual loss of tree cover ≥ 5 m height (2001-2024). Show yearly ",
            "methodology": "This data set, a collaboration between the GLAD (Global Land Analysis & Discovery) lab",
            "cautions": 'In this data set, "tree cover" is defined as all vegetation greater than 5 meters in height',
            "function_usage_notes": "Identifies areas of gross tree cover loss\n",
            "citation": 'Hansen et al., 2013. "High-Resolution Global Maps of 21st-Century Forest Cover Change." Accessed through Global Forest Watch on [date]. www.globalforestwatch.org\n',
        },
        "is_last_step": False,
        "remaining_steps": 20,
        "raw_data": {
            "USA.3.11": {
                4: {
                    "aoi_name": "Pima, Arizona, United States",
                    "dataset_name": "Tree cover loss",
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                    "country": [
                        "USA",
                        "USA",
                        "USA",
                        "USA",
                        "USA",
                        "USA",
                        "USA",
                        "USA",
                        "USA",
                        "USA",
                        "USA",
                        "USA",
                        "USA",
                        "USA",
                        "USA",
                        "USA",
                    ],
                    "region": [3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3],
                    "subregion": [
                        11,
                        11,
                        11,
                        11,
                        11,
                        11,
                        11,
                        11,
                        11,
                        11,
                        11,
                        11,
                        11,
                        11,
                        11,
                        11,
                    ],
                    "alert_date": [
                        "2024-07-02",
                        "2024-07-03",
                        "2024-07-05",
                        "2024-07-07",
                        "2024-07-10",
                        "2024-07-11",
                        "2024-07-12",
                        "2024-07-15",
                        "2024-07-17",
                        "2024-07-19",
                        "2024-07-20",
                        "2024-07-22",
                        "2024-07-25",
                        "2024-07-26",
                        "2024-07-27",
                        "2024-07-30",
                    ],
                    "confidence": [
                        "high",
                        "high",
                        "high",
                        "high",
                        "high",
                        "high",
                        "high",
                        "high",
                        "high",
                        "high",
                        "high",
                        "high",
                        "high",
                        "high",
                        "high",
                        "high",
                    ],
                    "value": [
                        133035.84375,
                        98698.4765625,
                        7198.0087890625,
                        427562.96875,
                        6532.4423828125,
                        427380.8125,
                        177973.953125,
                        10469.333984375,
                        842927.125,
                        325423.5,
                        4577.6240234375,
                        94053.0234375,
                        146477.453125,
                        439116.15625,
                        683501.1875,
                        142804.90625,
                    ],
                    "aoi_id": [
                        "USA.3.11",
                        "USA.3.11",
                        "USA.3.11",
                        "USA.3.11",
                        "USA.3.11",
                        "USA.3.11",
                        "USA.3.11",
                        "USA.3.11",
                        "USA.3.11",
                        "USA.3.11",
                        "USA.3.11",
                        "USA.3.11",
                        "USA.3.11",
                        "USA.3.11",
                        "USA.3.11",
                        "USA.3.11",
                    ],
                    "aoi_type": [
                        "admin",
                        "admin",
                        "admin",
                        "admin",
                        "admin",
                        "admin",
                        "admin",
                        "admin",
                        "admin",
                        "admin",
                        "admin",
                        "admin",
                        "admin",
                        "admin",
                        "admin",
                        "admin",
                    ],
                }
            },
            "CHE.2.12": {
                4: {
                    "aoi_name": "Bern, Switzerland",
                    "dataset_name": "Tree cover loss",
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                    "country": [
                        "CHE",
                        "CHE",
                        "CHE",
                        "CHE",
                        "CHE",
                        "CHE",
                        "CHE",
                        "CHE",
                        "CHE",
                        "CHE",
                        "CHE",
                        "CHE",
                        "CHE",
                        "CHE",
                        "CHE",
                        "CHE",
                    ],
                    "region": [3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3],
                    "subregion": [
                        11,
                        11,
                        11,
                        11,
                        11,
                        11,
                        11,
                        11,
                        11,
                        11,
                        11,
                        11,
                        11,
                        11,
                        11,
                        11,
                    ],
                    "alert_date": [
                        "2024-07-02",
                        "2024-07-03",
                        "2024-07-05",
                        "2024-07-07",
                        "2024-07-10",
                        "2024-07-11",
                        "2024-07-12",
                        "2024-07-15",
                        "2024-07-17",
                        "2024-07-19",
                        "2024-07-20",
                        "2024-07-22",
                        "2024-07-25",
                        "2024-07-26",
                        "2024-07-27",
                        "2024-07-30",
                    ],
                    "confidence": [
                        "high",
                        "high",
                        "high",
                        "high",
                        "high",
                        "high",
                        "high",
                        "high",
                        "high",
                        "high",
                        "high",
                        "high",
                        "high",
                        "high",
                        "high",
                        "high",
                    ],
                    "value": [
                        13335.84375,
                        9898.4765625,
                        798.0087890625,
                        42562.96875,
                        652.4423828125,
                        42380.8125,
                        17973.953125,
                        1049.333984375,
                        84927.125,
                        32423.5,
                        477.6240234375,
                        9453.0234375,
                        14647.453125,
                        43916.15625,
                        68501.1875,
                        14804.90625,
                    ],
                    "aoi_id": [
                        "CHE.2.12",
                        "CHE.2.12",
                        "CHE.2.12",
                        "CHE.2.12",
                        "CHE.2.12",
                        "CHE.2.12",
                        "CHE.2.12",
                        "CHE.2.12",
                        "CHE.2.12",
                        "CHE.2.12",
                        "CHE.2.12",
                        "CHE.2.12",
                        "CHE.2.12",
                        "CHE.2.12",
                        "CHE.2.12",
                        "CHE.2.12",
                    ],
                    "aoi_type": [
                        "admin",
                        "admin",
                        "admin",
                        "admin",
                        "admin",
                        "admin",
                        "admin",
                        "admin",
                        "admin",
                        "admin",
                        "admin",
                        "admin",
                        "admin",
                        "admin",
                        "admin",
                        "admin",
                    ],
                }
            },
        },
        "aoi_options": [
            {
                "source": "gadm",
                "src_id": "USA.3.11",
                "name": "Pima, Arizona, United States",
            },
            {
                "source": "gadm",
                "src_id": "CHE.2.12",
                "name": "Bern, Switzerland",
            },
        ],
    }
    command = await generate_insights.ainvoke(
        {
            "query": "Compare tree cover loss in Pima County, Arizona with Bern, Switzerland",
            "is_comparison": True,
            "tool_call_id": str(uuid.uuid4()),
            "state": update,
        }
    )

    assert "charts_data" in command.update
    assert "Pima" in command.update["insight"]["title"]
    assert "Bern" in command.update["insight"]["title"]


@pytest.mark.asyncio
async def test_simple_line_chart():
    """Test simple line chart generation for time series data."""
    mock_state_line = {
        "raw_data": {
            "BRA.15": {
                1: {
                    "aoi_name": "Amazon Region",
                    "dataset_name": "Deforestation Alerts",
                    "start_date": "2020-01-01",
                    "end_date": "2023-12-31",
                    "date": [
                        "2020-01-01",
                        "2021-01-01",
                        "2022-01-01",
                        "2023-01-01",
                    ],
                    "alerts": [1200, 1450, 1100, 980],
                    "region": ["Amazon", "Amazon", "Amazon", "Amazon"],
                }
            }
        },
        "dataset": {
            "prompt_instructions": "Analyze deforestation alert trends over time"
        },
        "aoi_options": [
            {
                "source": "gadm",
                "src_id": "Amazon Region",
                "name": "Amazon Region",
            }
        ],
    }

    result = await generate_insights.ainvoke(
        {
            "query": "What are the trends in deforestation alerts over time?",
            "is_comparison": False,
            "state": mock_state_line,
            "tool_call_id": str(uuid.uuid4()),
        }
    )

    assert "charts_data" in result.update
    assert len(result.update["charts_data"]) > 0

    chart_data = result.update["charts_data"][0]
    assert "data" in chart_data
    assert "id" in chart_data
    assert chart_data["type"] == "line"


@pytest.mark.asyncio
async def test_simple_bar_chart():
    """Test simple bar chart generation for categorical comparison."""
    mock_state_bar = {
        "raw_data": {
            "BRA.15": {
                1: {
                    "aoi_name": "Odisha",
                    "dataset_name": "Tree cover loss",
                    "start_date": "2022-01-01",
                    "end_date": "2022-12-31",
                    "districts": [
                        "Rayagada",
                        "Khurdha",
                        "Puri",
                        "Koraput",
                        "Ganjam",
                    ],
                    "forest_loss_ha": [
                        11568000,
                        6020000,
                        4770000,
                        1630000,
                        1240000,
                    ],
                    "year": [2022, 2022, 2022, 2022, 2022],
                }
            }
        },
        "dataset": {
            "prompt_instructions": "Compare forest loss"
        },
        "aoi_options": [
            {
                "source": "gadm",
                "src_id": "ODI",
                "name": "Tree cover loss",
            }
        ],
    }

    result = await generate_insights.ainvoke(
        {
            "query": "Which district have the highest forest loss in Odisha?",
            "is_comparison": False,
            "state": mock_state_bar,
            "tool_call_id": str(uuid.uuid4()),
        }
    )

    assert "charts_data" in result.update
    assert len(result.update["charts_data"]) > 0

    chart_data = result.update["charts_data"][0]
    assert "data" in chart_data
    assert "id" in chart_data
    assert chart_data["type"] == "bar"


@pytest.mark.asyncio
async def test_stacked_bar_chart():
    """Test stacked bar chart generation for composition data."""
    mock_state_stacked = {
        "raw_data": {
            "BRA.15": {
                1: {
                    "aoi_name": "Amazon Forest Loss Causes",
                    "dataset_name": "Forest Loss Causes Over Time",
                    "start_date": "2020-01-01",
                    "end_date": "2023-12-31",
                    "year": ["2020", "2021", "2022", "2023"],
                    "deforestation": [1200, 1100, 950, 800],
                    "fires": [800, 900, 1200, 1100],
                    "logging": [400, 350, 300, 250],
                    "agriculture": [600, 700, 800, 750],
                    "region": ["Amazon", "Amazon", "Amazon", "Amazon"],
                }
            }
        },
        "dataset": {
            "prompt_instructions": "Analyze composition of forest loss causes over time"
        },
        "aoi_options": [
            {
                "source": "gadm",
                "src_id": "Amazon Forest Loss Causes",
                "name": "Amazon Forest Loss Causes",
            }
        ],
    }

    result = await generate_insights.ainvoke(
        {
            "query": "Show me the composition of forest loss causes over time as a stacked bar chart",
            "is_comparison": False,
            "state": mock_state_stacked,
            "tool_call_id": str(uuid.uuid4()),
        }
    )

    assert "charts_data" in result.update
    assert len(result.update["charts_data"]) > 0

    chart_data = result.update["charts_data"][0]
    assert "data" in chart_data
    assert "id" in chart_data
    assert chart_data["type"] == "stacked-bar"


@pytest.mark.asyncio
async def test_grouped_bar_chart():
    """Test grouped bar chart generation for multiple metrics comparison."""
    mock_state_grouped = {
        "raw_data": {
            "BRA.15": {
                1: {
                    "aoi_name": "Global Forest Metrics",
                    "dataset_name": "Forest Loss and Fire Incidents",
                    "start_date": "2022-01-01",
                    "end_date": "2022-12-31",
                    "country": [
                        "Brazil",
                        "Brazil",
                        "Indonesia",
                        "Indonesia",
                        "DRC",
                        "DRC",
                    ],
                    "metric": [
                        "Forest Loss",
                        "Fire Incidents",
                        "Forest Loss",
                        "Fire Incidents",
                        "Forest Loss",
                        "Fire Incidents",
                    ],
                    "value": [11568, 8500, 6020, 4200, 4770, 2100],
                    "year": [2022, 2022, 2022, 2022, 2022, 2022],
                }
            }
        },
        "dataset": {
            "prompt_instructions": "Compare forest loss and fire incidents across countries"
        },
        "aoi_options": [
            {
                "source": "gadm",
                "src_id": "Global Forest Metrics",
                "name": "Global Forest Metrics",
            }
        ],
    }

    result = await generate_insights.ainvoke(
        {
            "query": "Compare forest loss and fire incidents across countries using grouped bars",
            "is_comparison": False,
            "state": mock_state_grouped,
            "tool_call_id": str(uuid.uuid4()),
        }
    )

    assert "charts_data" in result.update
    assert len(result.update["charts_data"]) > 0

    chart_data = result.update["charts_data"][0]
    assert "data" in chart_data
    assert "id" in chart_data
    assert chart_data["type"] == "grouped-bar"


@pytest.mark.asyncio
async def test_pie_chart():
    """Test pie chart generation for part-to-whole relationship."""
    mock_state_pie = {
        "raw_data": {
            "BRA.15": {
                1: {
                    "aoi_name": "Global Forest Loss Causes",
                    "dataset_name": "Global Forest Loss Causes",
                    "start_date": "2022-01-01",
                    "end_date": "2022-12-31",
                    "cause": [
                        "Deforestation",
                        "Fires",
                        "Logging",
                        "Agriculture",
                        "Mining",
                    ],
                    "percentage": [45, 25, 15, 10, 5],
                    "region": [
                        "Global",
                        "Global",
                        "Global",
                        "Global",
                        "Global",
                    ],
                }
            }
        },
        "dataset": {
            "prompt_instructions": "Analyze main causes of forest loss globally"
        },
        "aoi_options": [
            {
                "source": "gadm",
                "src_id": "Global Forest Loss Causes",
                "name": "Global Forest Loss Causes",
            }
        ],
    }

    result = await generate_insights.ainvoke(
        {
            "query": "What are the main causes of forest loss globally? Show as pie chart",
            "is_comparison": False,
            "state": mock_state_pie,
            "tool_call_id": str(uuid.uuid4()),
        }
    )

    assert "charts_data" in result.update
    assert len(result.update["charts_data"]) > 0

    chart_data = result.update["charts_data"][0]
    assert "data" in chart_data
    assert "id" in chart_data
    assert chart_data["type"] == "pie"
