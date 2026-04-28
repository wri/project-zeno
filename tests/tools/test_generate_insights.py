import sys
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

from src.agent.state import Statistics
from src.agent.tools.datasets_config import DATASETS as _ALL_DATASETS
from src.agent.tools.generate_insights import generate_insights

_DS_BY_ID = {ds["dataset_id"]: ds for ds in _ALL_DATASETS}


def _dataset_fields(dataset_id: int, context_layer=None) -> dict:
    ds = _DS_BY_ID[dataset_id]
    result = {
        "dataset_id": ds["dataset_id"],
        "dataset_name": ds["dataset_name"],
        "context_layer": context_layer,
        "tile_url": ds.get("tile_url", ""),
        "analytics_api_endpoint": ds.get("analytics_api_endpoint", ""),
        "description": ds.get("description", ""),
        "prompt_instructions": ds.get("prompt_instructions", ""),
        "methodology": ds.get("methodology", ""),
        "cautions": ds.get("cautions", ""),
        "function_usage_notes": ds.get("function_usage_notes", ""),
        "citation": ds.get("citation", ""),
    }
    for field in (
        "selection_hints",
        "code_instructions",
        "presentation_instructions",
    ):
        val = ds.get(field)
        if val:
            result[field] = val
    return result


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
                dataset_name="Tree cover loss",
                source_url="http://example.com/analytics/bafa3df8-343e-53fe-8c51-9c59c600d72f",
                start_date="2024-07-01",
                end_date="2024-07-31",
                aoi_names=[
                    "Pima, Arizona, United States",
                    "Bern, Switzerland",
                ],
                data={
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
                },
            ),
            Statistics(
                dataset_name="Tree cover loss",
                source_url="http://example.com/analytics/bafa3df8-343e-53fe-8c51-9c59c600d72f",
                start_date="2024-07-01",
                end_date="2024-07-31",
                aoi_names=["Bern, Switzerland"],
                data={
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
                },
            ),
        ],
    }
    tool_call_id = str(uuid.uuid4())
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
                dataset_name="Deforestation Alerts",
                source_url="http://example.com/analytics/bafa3df8-343e-53fe-8c51-9c59c600d72f",
                start_date="2020-01-01",
                end_date="2023-12-31",
                aoi_names=["Amazon Region"],
                data={
                    "alert_date": [
                        "2020-01-01",
                        "2021-01-01",
                        "2022-01-01",
                        "2023-01-01",
                    ],
                    "value": [1200, 1450, 1100, 980],
                    "aoi_id": ["BRA.15", "BRA.15", "BRA.15", "BRA.15"],
                    "aoi_type": ["admin", "admin", "admin", "admin"],
                },
            )
        ],
    }

    tool_call_id = str(uuid.uuid4())
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
                dataset_name="Tree cover loss",
                source_url="http://example.com/analytics/bafa3df8-343e-53fe-8c51-9c59c600d72f",
                start_date="2022-01-01",
                end_date="2022-12-31",
                aoi_names=["Odisha, India"],
                data={
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
                },
            )
        ],
    }

    tool_call_id = str(uuid.uuid4())
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
                dataset_name="Forest Loss Causes Over Time",
                source_url="http://example.com/analytics/bafa3df8-343e-53fe-8c51-9c59c600d72f",
                start_date="2020-01-01",
                end_date="2023-12-31",
                aoi_names=["Amazon Region, Brazil"],
                data={
                    "year": ["2020", "2021", "2022", "2023"],
                    "deforestation": [1200, 1100, 950, 800],
                    "fires": [800, 900, 1200, 1100],
                    "logging": [400, 350, 300, 250],
                    "agriculture": [600, 700, 800, 750],
                    "aoi_id": ["BRA.15"] * 4,
                    "aoi_type": ["admin"] * 4,
                },
            )
        ],
    }

    tool_call_id = str(uuid.uuid4())
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
                dataset_name="Forest Loss and Fire Incidents",
                source_url="http://example.com/analytics/bafa3df8-343e-53fe-8c51-9c59c600d72f",
                start_date="2022-01-01",
                end_date="2022-12-31",
                aoi_names=[
                    "Brazil",
                    "Indonesia",
                    "Democratic Republic of Congo",
                ],
                data={
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
                },
            )
        ],
    }

    tool_call_id = str(uuid.uuid4())
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
                dataset_name="Global Forest Loss Causes",
                source_url="http://example.com/analytics/bafa3df8-343e-53fe-8c51-9c59c600d72f",
                start_date="2022-01-01",
                end_date="2022-12-31",
                aoi_names=["Global"],
                data={
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
                },
            )
        ],
    }

    tool_call_id = str(uuid.uuid4())
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


_TCL_STATISTICS = Statistics(
    dataset_name="Tree cover loss",
    source_url="http://example.com/analytics/tcl-test",
    start_date="2015-01-01",
    end_date="2022-12-31",
    aoi_names=["Pará, Brazil"],
    data={
        "year": [2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022],
        "area_ha": [
            798045,
            688012,
            654321,
            723456,
            891034,
            812345,
            746231,
            701234,
        ],
        "carbon_emissions_MgCO2e": [
            354021,
            302456,
            289012,
            318765,
            395432,
            360123,
            331098,
            310456,
        ],
        "aoi_id": ["BRA.14"] * 8,
        "aoi_type": ["admin"] * 8,
    },
)

_TCL_QUERY_VARIANTS = [
    "What is the trend in tree cover loss in Pará, Brazil from 2015 to 2022?",
    "How much tree cover was lost each year in Pará, Brazil?",
    "Show annual tree cover loss and carbon emissions "
    "for Pará, Brazil from 2015 to 2022.",
]


@pytest.mark.parametrize("query", _TCL_QUERY_VARIANTS)
async def test_tcl_always_produces_two_bar_charts(query):
    """TCL must always return exactly 2 bar charts (loss + emissions)
    regardless of query phrasing.

    These queries are parameterized to expose nondeterministic behaviour
    in the current code_instructions: trend phrasing → line chart;
    single-metric phrasing → missing emissions chart.
    """
    state = {
        "dataset": _dataset_fields(4),
        "statistics": [_TCL_STATISTICS],
    }

    tool_call_id = str(uuid.uuid4())
    result = await generate_insights.ainvoke(
        {
            "type": "tool_call",
            "name": "generate_insights",
            "id": tool_call_id,
            "args": {"query": query, "state": state},
        }
    )

    assert "charts_data" in result.update
    charts = result.update["charts_data"]
    assert len(charts) == 2, f"Expected exactly 2 charts, got {len(charts)}"

    y_axes = set()
    for idx, chart in enumerate(charts):
        assert "id" in chart, f"Chart {idx} is missing 'id': {chart}"
        assert "data" in chart, f"Chart {idx} is missing 'data': {chart}"
        assert (
            chart.get("type") == "bar"
        ), f"Chart {idx} type is '{chart.get('type')}', expected 'bar'. Chart: {chart}"
        y_axis = chart.get("yAxis")
        assert y_axis, f"Chart {idx} is missing 'yAxis': {chart}"
        y_axes.add(y_axis)

    expected_metrics = {"area_ha", "carbon_emissions_MgCO2e"}
    assert (
        y_axes == expected_metrics
    ), f"Expected charts to map to {expected_metrics}, but got {y_axes}. Charts: {charts}"


_TCL_STATISTICS_MULTIREGION_2024 = Statistics(
    dataset_name="Tree cover loss",
    source_url="http://example.com/analytics/tcl-brazil-2024",
    start_date="2024-01-01",
    end_date="2024-12-31",
    aoi_names=[
        "Pará, Brazil",
        "Amazonas, Brazil",
        "Mato Grosso, Brazil",
        "Rondônia, Brazil",
        "Acre, Brazil",
    ],
    data={
        "year": [2024] * 5,
        "name": ["Pará", "Amazonas", "Mato Grosso", "Rondônia", "Acre"],
        "area_ha": [798045.0, 456123.0, 612890.0, 234567.0, 145678.0],
        "carbon_emissions_MgCO2e": [
            354021000.0,
            202456000.0,
            271765000.0,
            104123000.0,
            64598000.0,
        ],
        "aoi_id": ["BRA.14", "BRA.3", "BRA.28", "BRA.52", "BRA.4"],
        "aoi_type": ["admin"] * 5,
    },
)


@pytest.mark.parametrize(
    "query",
    [
        "Which Brazilian states had the highest tree cover loss in 2024?",
        "Compare tree cover loss across Pará, Amazonas, and Mato Grosso in 2024",
        "Show 2024 tree cover loss by region in Brazil",
    ],
)
async def test_tcl_case2_multiregion_single_year(query):
    """TCL Case 2: Multiple AOIs at a single time point (cross-sectional)."""
    state = {
        "dataset": _dataset_fields(4),
        "statistics": [_TCL_STATISTICS_MULTIREGION_2024],
    }

    tool_call_id = str(uuid.uuid4())
    result = await generate_insights.ainvoke(
        {
            "type": "tool_call",
            "name": "generate_insights",
            "id": tool_call_id,
            "args": {"query": query, "state": state},
        }
    )

    assert "charts_data" in result.update
    charts = result.update["charts_data"]
    assert len(charts) == 2, f"Expected exactly 2 charts, got {len(charts)}"

    y_axes = set()
    for idx, chart in enumerate(charts):
        assert "id" in chart, f"Chart {idx} is missing 'id': {chart}"
        assert "data" in chart, f"Chart {idx} is missing 'data': {chart}"
        assert (
            chart.get("type") == "bar"
        ), f"Chart {idx} type is '{chart.get('type')}', expected 'bar'. Chart: {chart}"
        y_axis = chart.get("yAxis")
        assert y_axis, f"Chart {idx} is missing 'yAxis': {chart}"
        y_axes.add(y_axis)

    expected_metrics = {"area_ha", "carbon_emissions_MgCO2e"}
    assert (
        y_axes == expected_metrics
    ), f"Expected charts to map to {expected_metrics}, but got {y_axes}. Charts: {charts}"
