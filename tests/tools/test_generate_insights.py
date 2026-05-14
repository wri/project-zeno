import sys
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

from src.agent.state import Statistics
from src.agent.tools.generate_insights import generate_insights

# Use session-scoped event loop to match conftest.py fixtures and avoid
# "Event loop is closed" errors when running with other test modules
pytestmark = pytest.mark.asyncio(loop_scope="session")

_FETCH_PATCH = "src.agent.tools.generate_insights.fetch_statistics_from_url"


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


@pytest.fixture(scope="module", autouse=True)
def reset_google_clients():
    """Reset cached Google clients at module start to use the correct event loop."""
    llms_module = sys.modules["src.agent.llms"]
    llms_module.SMALL_MODEL = llms_module.get_small_model()
    yield


def _mock_session_factory():
    """Create a mock async session that captures InsightOrm rows."""
    session = AsyncMock()

    async def fake_refresh(row):
        if not row.id:
            row.id = uuid.uuid4()

    session.refresh = fake_refresh
    return session


@pytest.fixture(autouse=True)
def mock_insight_db():
    mock_session = _mock_session_factory()

    @asynccontextmanager
    async def fake_pool():
        yield mock_session

    with patch(
        "src.agent.tools.generate_insights.get_session_from_pool",
        fake_pool,
    ):
        yield mock_session


async def test_generate_insights_comparison():
    usa_data = {
        "country": ["USA"] * 16,
        "region": [3] * 16,
        "subregion": [11] * 16,
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
        "confidence": ["high"] * 16,
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
        "aoi_id": ["USA.3.11"] * 16,
        "aoi_type": ["admin"] * 16,
    }
    che_data = {
        "country": ["CHE"] * 16,
        "region": [3] * 16,
        "subregion": [11] * 16,
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
        "confidence": ["high"] * 16,
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
        "aoi_id": ["CHE.2.12"] * 16,
        "aoi_type": ["admin"] * 16,
    }
    update = {
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
        "statistics": [
            Statistics(
                id="a1b2c3d4-0001-0001-0001-000000000001",
                dataset_name="Tree cover loss",
                source_url="http://example.com/analytics/usa-pima-july-2024",
                start_date="2024-07-01",
                end_date="2024-07-31",
                aoi_names=[
                    "Pima, Arizona, United States",
                    "Bern, Switzerland",
                ],
            ),
            Statistics(
                id="a1b2c3d4-0001-0001-0001-000000000002",
                dataset_name="Tree cover loss",
                source_url="http://example.com/analytics/che-bern-july-2024",
                start_date="2024-07-01",
                end_date="2024-07-31",
                aoi_names=["Bern, Switzerland"],
            ),
        ],
    }
    tool_call_id = str(uuid.uuid4())
    with patch(_FETCH_PATCH, new=AsyncMock(side_effect=[usa_data, che_data])):
        command = await generate_insights.ainvoke(
            {
                "type": "tool_call",
                "name": "generate_insights",
                "id": tool_call_id,
                "args": {
                    "query": "Compare tree cover loss in Pima County, Arizona with Bern, Switzerland",
                    "state": update,
                },
            }
        )

    assert "insight_id" in command.update
    assert command.update["insight_id"]
    assert "charts_data" in command.update
    assert len(command.update["charts_data"]) > 0

    # Backwards-compat: inline state fields coexist with insight_id
    chart = command.update["charts_data"][0]
    assert "type" in chart
    assert "data" in chart
    assert "title" in chart
    assert isinstance(command.update.get("codeact_parts"), list)
    assert isinstance(command.update.get("insight"), str)
    assert len(command.update["insight"]) > 0
    assert isinstance(command.update.get("follow_up_suggestions"), list)


async def test_simple_line_chart():
    """Test simple line chart generation for time series data."""
    line_data = {
        "alert_date": [
            "2020-01-01",
            "2021-01-01",
            "2022-01-01",
            "2023-01-01",
        ],
        "value": [1200, 1450, 1100, 980],
        "aoi_id": ["BRA.15", "BRA.15", "BRA.15", "BRA.15"],
        "aoi_type": ["admin", "admin", "admin", "admin"],
    }
    mock_state_line = {
        "dataset": {
            "dataset_id": 1,
            "context_layer": None,
            "date_request_match": True,
            "reason": "Deforestation alerts dataset matches the request for analyzing alert trends.",
            "tile_url": "https://tiles.example.com/deforestation/latest/dynamic/{z}/{x}/{y}.png",
            "dataset_name": "Deforestation Alerts",
            "analytics_api_endpoint": "/v0/deforestation/alerts/analytics",
            "description": "Deforestation alerts tracking forest loss events.",
            "prompt_instructions": "Analyze deforestation alert trends over time",
            "methodology": "Satellite-based detection of forest loss events.",
            "cautions": "Alert data may have temporal lag.",
            "function_usage_notes": "Identifies deforestation events\n",
            "citation": "Global Forest Watch Deforestation Alerts.",
        },
        "statistics": [
            Statistics(
                id="a1b2c3d4-0002-0002-0002-000000000001",
                dataset_name="Deforestation Alerts",
                source_url="http://example.com/analytics/deforestation-amazon-2020-2023",
                start_date="2020-01-01",
                end_date="2023-12-31",
                aoi_names=["Amazon Region"],
            )
        ],
    }

    tool_call_id = str(uuid.uuid4())
    with patch(_FETCH_PATCH, new=AsyncMock(return_value=line_data)):
        result = await generate_insights.ainvoke(
            {
                "type": "tool_call",
                "name": "generate_insights",
                "id": tool_call_id,
                "args": {
                    "query": "What are the trends in deforestation alerts over time?",
                    "state": mock_state_line,
                },
            }
        )

    assert "insight_id" in result.update
    assert result.update["insight_id"]
    assert "charts_data" in result.update
    assert len(result.update["charts_data"]) > 0


async def test_simple_bar_chart():
    """Test simple bar chart generation for categorical comparison."""
    bar_data = {
        "subregion": [
            "Rayagada",
            "Khurdha",
            "Puri",
            "Koraput",
            "Ganjam",
        ],
        "value": [
            11568000,
            6020000,
            4770000,
            1630000,
            1240000,
        ],
        "year": [2022, 2022, 2022, 2022, 2022],
        "aoi_id": ["IND.26"] * 5,
        "aoi_type": ["admin"] * 5,
    }
    mock_state_bar = {
        "dataset": {
            "dataset_id": 4,
            "context_layer": None,
            "date_request_match": True,
            "reason": "Tree cover loss dataset matches the request for forest loss analysis.",
            "tile_url": "https://tiles.globalforestwatch.org/umd_tree_cover_loss/latest/dynamic/{z}/{x}/{y}.png",
            "dataset_name": "Tree cover loss",
            "analytics_api_endpoint": "/v0/land_change/tree_cover_loss/analytics",
            "description": "Tree Cover Loss (Hansen/UMD/GLAD) maps annual global forest loss.",
            "prompt_instructions": "Compare forest loss across districts",
            "methodology": "Satellite-based detection of tree cover loss.",
            "cautions": "Tree cover includes all vegetation greater than 5 meters.",
            "function_usage_notes": "Identifies areas of gross tree cover loss\n",
            "citation": "Hansen et al., 2013.",
        },
        "statistics": [
            Statistics(
                id="a1b2c3d4-0003-0003-0003-000000000001",
                dataset_name="Tree cover loss",
                source_url="http://example.com/analytics/tree-cover-loss-odisha-2022",
                start_date="2022-01-01",
                end_date="2022-12-31",
                aoi_names=["Odisha, India"],
            )
        ],
    }

    tool_call_id = str(uuid.uuid4())
    with patch(_FETCH_PATCH, new=AsyncMock(return_value=bar_data)):
        result = await generate_insights.ainvoke(
            {
                "type": "tool_call",
                "name": "generate_insights",
                "id": tool_call_id,
                "args": {
                    "query": "Which district have the highest forest loss in Odisha?",
                    "state": mock_state_bar,
                },
            }
        )

    assert "insight_id" in result.update
    assert result.update["insight_id"]
    assert "charts_data" in result.update
    assert len(result.update["charts_data"]) > 0


async def test_stacked_bar_chart():
    """Test stacked bar chart generation for composition data."""
    stacked_data = {
        "year": ["2020", "2021", "2022", "2023"],
        "deforestation": [1200, 1100, 950, 800],
        "fires": [800, 900, 1200, 1100],
        "logging": [400, 350, 300, 250],
        "agriculture": [600, 700, 800, 750],
        "aoi_id": ["BRA.15"] * 4,
        "aoi_type": ["admin"] * 4,
    }
    mock_state_stacked = {
        "dataset": {
            "dataset_id": 5,
            "context_layer": None,
            "date_request_match": True,
            "reason": "Forest loss causes dataset matches the request for composition analysis.",
            "tile_url": "https://tiles.example.com/forest_loss_causes/latest/dynamic/{z}/{x}/{y}.png",
            "dataset_name": "Forest Loss Causes Over Time",
            "analytics_api_endpoint": "/v0/forest/loss_causes/analytics",
            "description": "Breakdown of forest loss by cause over time.",
            "prompt_instructions": "Analyze composition of forest loss causes over time",
            "methodology": "Attribution of forest loss to different drivers.",
            "cautions": "Cause attribution may have uncertainty.",
            "function_usage_notes": "Identifies drivers of forest loss\n",
            "citation": "Forest Loss Attribution Study.",
        },
        "statistics": [
            Statistics(
                id="a1b2c3d4-0004-0004-0004-000000000001",
                dataset_name="Forest Loss Causes Over Time",
                source_url="http://example.com/analytics/forest-loss-causes-amazon-2020-2023",
                start_date="2020-01-01",
                end_date="2023-12-31",
                aoi_names=["Amazon Region, Brazil"],
            )
        ],
    }

    tool_call_id = str(uuid.uuid4())
    with patch(_FETCH_PATCH, new=AsyncMock(return_value=stacked_data)):
        result = await generate_insights.ainvoke(
            {
                "type": "tool_call",
                "name": "generate_insights",
                "id": tool_call_id,
                "args": {
                    "query": "Show me the composition of forest loss causes over time as a stacked bar chart",
                    "state": mock_state_stacked,
                },
            }
        )

    assert "insight_id" in result.update
    assert result.update["insight_id"]
    assert "charts_data" in result.update
    assert len(result.update["charts_data"]) > 0


async def test_grouped_bar_chart():
    """Test grouped bar chart generation for multiple metrics comparison."""
    grouped_data = {
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
        "year": [2022] * 6,
        "aoi_id": ["BRA", "BRA", "IDN", "IDN", "COD", "COD"],
        "aoi_type": ["admin"] * 6,
    }
    mock_state_grouped = {
        "dataset": {
            "dataset_id": 6,
            "context_layer": None,
            "date_request_match": True,
            "reason": "Forest metrics dataset matches the request for comparing loss and fire incidents.",
            "tile_url": "https://tiles.example.com/forest_metrics/latest/dynamic/{z}/{x}/{y}.png",
            "dataset_name": "Forest Loss and Fire Incidents",
            "analytics_api_endpoint": "/v0/forest/metrics/analytics",
            "description": "Combined forest loss and fire incident metrics.",
            "prompt_instructions": "Compare forest loss and fire incidents across countries",
            "methodology": "Satellite-based detection of forest loss and fire events.",
            "cautions": "Metrics may have different temporal resolutions.",
            "function_usage_notes": "Compares forest metrics across regions\n",
            "citation": "Global Forest Metrics Study.",
        },
        "statistics": [
            Statistics(
                id="a1b2c3d4-0005-0005-0005-000000000001",
                dataset_name="Forest Loss and Fire Incidents",
                source_url="http://example.com/analytics/forest-metrics-bra-idn-cod-2022",
                start_date="2022-01-01",
                end_date="2022-12-31",
                aoi_names=[
                    "Brazil",
                    "Indonesia",
                    "Democratic Republic of Congo",
                ],
            )
        ],
    }

    tool_call_id = str(uuid.uuid4())
    with patch(_FETCH_PATCH, new=AsyncMock(return_value=grouped_data)):
        result = await generate_insights.ainvoke(
            {
                "type": "tool_call",
                "name": "generate_insights",
                "id": tool_call_id,
                "args": {
                    "query": "Compare forest loss and fire incidents across countries using grouped bars",
                    "state": mock_state_grouped,
                },
            }
        )

    assert "insight_id" in result.update
    assert result.update["insight_id"]
    assert "charts_data" in result.update
    assert len(result.update["charts_data"]) > 0


async def test_pie_chart():
    """Test pie chart generation for part-to-whole relationship."""
    pie_data = {
        "cause": [
            "Deforestation",
            "Fires",
            "Logging",
            "Agriculture",
            "Mining",
        ],
        "value": [45, 25, 15, 10, 5],
        "aoi_id": ["GLOBAL"] * 5,
        "aoi_type": ["global"] * 5,
    }
    mock_state_pie = {
        "dataset": {
            "dataset_id": 7,
            "context_layer": None,
            "date_request_match": True,
            "reason": "Forest loss causes dataset matches the request for global cause analysis.",
            "tile_url": "https://tiles.example.com/forest_loss_causes/latest/dynamic/{z}/{x}/{y}.png",
            "dataset_name": "Global Forest Loss Causes",
            "analytics_api_endpoint": "/v0/forest/loss_causes/analytics",
            "description": "Global breakdown of forest loss by cause.",
            "prompt_instructions": "Analyze main causes of forest loss globally",
            "methodology": "Attribution of global forest loss to different drivers.",
            "cautions": "Cause attribution may have regional variations.",
            "function_usage_notes": "Identifies global drivers of forest loss\n",
            "citation": "Global Forest Loss Attribution Study.",
        },
        "statistics": [
            Statistics(
                id="a1b2c3d4-0006-0006-0006-000000000001",
                dataset_name="Global Forest Loss Causes",
                source_url="http://example.com/analytics/forest-loss-causes-global-2022",
                start_date="2022-01-01",
                end_date="2022-12-31",
                aoi_names=["Global"],
            )
        ],
    }

    tool_call_id = str(uuid.uuid4())
    with patch(_FETCH_PATCH, new=AsyncMock(return_value=pie_data)):
        result = await generate_insights.ainvoke(
            {
                "type": "tool_call",
                "name": "generate_insights",
                "id": tool_call_id,
                "args": {
                    "query": "What are the main causes of forest loss globally? Show as pie chart",
                    "state": mock_state_pie,
                },
            }
        )

    assert "insight_id" in result.update
    assert result.update["insight_id"]
    assert "charts_data" in result.update
    assert len(result.update["charts_data"]) > 0

    chart_data = result.update["charts_data"][0]
    assert "data" in chart_data
    assert "id" in chart_data
    assert chart_data["type"] == "pie"


async def test_generate_insights_creates_two_bar_charts_with_code_instructions():
    """Test multi-chart generation with generic fields and aligned code instructions."""
    multichart_data = {
        "year": [
            2021,
            2022,
            2023,
            2024,
        ],
        "metric_primary": [
            120,
            150,
            180,
            210,
        ],
        "metric_secondary": [
            80,
            95,
            110,
            130,
        ],
        "aoi_id": ["REG.1"] * 4,
        "aoi_type": ["admin"] * 4,
    }
    mock_state_multichart = {
        "dataset": {
            "dataset_id": 999,
            "context_layer": None,
            "date_request_match": True,
            "reason": "The dataset contains two annual metrics and supports side-by-side trend analysis.",
            "tile_url": "https://tiles.example.com/generic_metrics/latest/dynamic/{z}/{x}/{y}.png",
            "dataset_name": "Generic Annual Metrics",
            "analytics_api_endpoint": "/v0/generic/metrics/analytics",
            "description": "Synthetic yearly metrics for multi-chart testing.",
            "prompt_instructions": "Analyze annual trends for both metrics.",
            "code_instructions": "Generate exactly 2 separate bar charts (year, metric_primary) and (year, metric_secondary).",
            "presentation_instructions": "Use neutral wording and keep axis mappings tied to existing columns.",
            "methodology": "Synthetic data for test validation.",
            "cautions": "Values are synthetic and for test behavior only.",
            "function_usage_notes": "Supports multi-chart behavior validation\n",
            "citation": "Internal synthetic test dataset.",
        },
        "statistics": [
            Statistics(
                id="a1b2c3d4-0007-0007-0007-000000000001",
                dataset_name="Generic Annual Metrics",
                source_url="http://example.com/analytics/generic-annual-metrics-reg1-2021-2024",
                start_date="2021-01-01",
                end_date="2024-12-31",
                aoi_names=["Sample Region"],
            )
        ],
    }

    tool_call_id = str(uuid.uuid4())
    with patch(_FETCH_PATCH, new=AsyncMock(return_value=multichart_data)):
        result = await generate_insights.ainvoke(
            {
                "type": "tool_call",
                "name": "generate_insights",
                "id": tool_call_id,
                "args": {
                    "query": "What is the trend in this region over the last four years?",
                    "state": mock_state_multichart,
                },
            }
        )

    assert "charts_data" in result.update
    charts = result.update["charts_data"]
    assert len(charts) == 2, f"Expected exactly 2 charts, got {len(charts)}"

    for idx, chart in enumerate(charts):
        assert "id" in chart, f"Chart {idx} is missing 'id': {chart}"
        assert "data" in chart, f"Chart {idx} is missing 'data': {chart}"
        assert (
            chart.get("type") == "bar"
        ), f"Chart {idx} type is '{chart.get('type')}', expected 'bar'. Chart: {chart}"
