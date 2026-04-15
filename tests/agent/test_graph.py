import sys
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest

from src.agent.graph import fetch_zeno_anonymous
from src.agent.tools.datasets_config import DATASETS

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


@pytest.fixture(scope="function", autouse=True)
def user():
    """Override the global user fixture to avoid database connections."""
    pass


@pytest.fixture(scope="function", autouse=True)
def user_ds():
    """Override the global user_ds fixture to avoid database connections."""
    pass


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
    """Mock insight DB writes to avoid requiring a real global pool."""
    mock_session = _mock_session_factory()

    @asynccontextmanager
    async def fake_pool():
        yield mock_session

    with patch(
        "src.agent.tools.generate_insights.get_session_from_pool",
        fake_pool,
    ):
        yield mock_session


@pytest.fixture(scope="function", autouse=True)
def mock_query_aoi_database():
    """Mock query_aoi_database to return MOCK_AOI_QUERY_RESULTS_PARA_BRAZIL."""

    async def _return_mock_df(_place_name, result_limit=10):
        if "Parana" in _place_name or "Paraná" in _place_name:
            print("Returning MOCK_AOI_QUERY_RESULTS_PARANA")
            return MOCK_AOI_QUERY_RESULTS_PARANA.copy()
        if "Para" in _place_name:
            print("Returning MOCK_AOI_QUERY_RESULTS_PARA_BRAZIL")
            return MOCK_AOI_QUERY_RESULTS_PARA_BRAZIL.copy()
        return MOCK_AOI_QUERY_RESULTS_PARA_BRAZIL.copy()

    with patch(
        "src.agent.tools.pick_aoi.tool.query_aoi_database",
        new_callable=AsyncMock,
        side_effect=_return_mock_df,
    ):
        yield


@pytest.fixture(scope="function", autouse=True)
def mock_query_subregion_database():
    """Mock query_subregion_database to avoid global DB pool in agent tests."""

    async def _return_mock_df(subregion_name, source, src_id):
        return pd.DataFrame(
            [
                {
                    "name": f"Mock {subregion_name}",
                    "subtype": "site"
                    if source in ("kba", "wdpa", "landmark")
                    else "district-county",
                    "src_id": src_id,
                    "source": source,
                }
            ]
        )

    with patch(
        "src.agent.tools.pick_aoi.tool.query_subregion_database",
        new_callable=AsyncMock,
        side_effect=_return_mock_df,
    ):
        yield


MOCK_AOI_QUERY_RESULTS_PARA_BRAZIL = pd.DataFrame(
    {
        "src_id": {
            0: "BRA.16_1",
            1: "BRA.14_1",
            2: "BRA.15_1",
            3: "BRA.15.12_2",
            4: "BRA",
            5: "BRA.15.133_2",
            6: "BRA.16.266_2",
            7: "BRA.14.144_2",
            8: "BRA.16.183_2",
            9: "BRA.15.84_2",
        },
        "name": {
            0: "Paraná, Brazil",
            1: "Pará, Brazil",
            2: "Paraíba, Brazil",
            3: "Arara, Paraíba, Brazil",
            4: "Brazil",
            5: "Parari, Paraíba, Brazil",
            6: "Piên, Paraná, Brazil",
            7: "Xinguara, Pará, Brazil",
            8: "Jussara, Paraná, Brazil",
            9: "Ibiara, Paraíba, Brazil",
        },
        "subtype": {
            0: "state-province",
            1: "state-province",
            2: "state-province",
            3: "district-county",
            4: "country",
            5: "district-county",
            6: "district-county",
            7: "district-county",
            8: "district-county",
            9: "district-county",
        },
        "source": {
            0: "gadm",
            1: "gadm",
            2: "gadm",
            3: "gadm",
            4: "gadm",
            5: "gadm",
            6: "gadm",
            7: "gadm",
            8: "gadm",
            9: "gadm",
        },
        "similarity_score": {
            0: 0.7333333492279053,
            1: 0.7142857313156128,
            2: 0.6875,
            3: 0.6315789222717285,
            4: 0.5833333134651184,
            5: 0.5789473652839661,
            6: 0.5789473652839661,
            7: 0.5714285969734192,
            8: 0.5714285969734192,
            9: 0.5714285969734192,
        },
    }
)

MOCK_AOI_QUERY_RESULTS_PARANA = pd.DataFrame(
    {
        "src_id": {
            0: "PRY",
            1: "BRA.16.370_2",
            2: "BRA.16.18_2",
            3: "BRA.16_1",
            4: "BRA.16.194_2",
            5: "BRA.16.257_2",
            6: "BRA.16.255_2",
            7: "BRA.16.13_2",
            8: "BRA.16.254_2",
            9: "MEX15381",
        },
        "name": {
            0: "Paraguay",
            1: "Tamarana, Paraná, Brazil",
            2: "Apucarana, Paraná, Brazil",
            3: "Paraná, Brazil",
            4: "Luiziana, Paraná, Brazil",
            5: "Paranavaí, Paraná, Brazil",
            6: "Paranaguá, Paraná, Brazil",
            7: "Anahy, Paraná, Brazil",
            8: "Paranacity, Paraná, Brazil",
            9: "El Paranal, Ejido, MEX",
        },
        "subtype": {
            0: "country",
            1: "district-county",
            2: "district-county",
            3: "state-province",
            4: "district-county",
            5: "district-county",
            6: "district-county",
            7: "district-county",
            8: "district-county",
            9: "indigenous-and-community-land",
        },
        "source": {
            0: "gadm",
            1: "gadm",
            2: "gadm",
            3: "gadm",
            4: "gadm",
            5: "gadm",
            6: "gadm",
            7: "gadm",
            8: "gadm",
            9: "landmark",
        },
        "similarity_score": {
            0: 0.3333333432674408,
            1: 0.3333333432674408,
            2: 0.3181818127632141,
            3: 0.3125,
            4: 0.30434781312942505,
            5: 0.30000001192092896,
            6: 0.30000001192092896,
            7: 0.2857142984867096,
            8: 0.2857142984867096,
            9: 0.2857142984867096,
        },
    }
)


_ordered = [
    next(d for d in DATASETS if d["dataset_id"] == i) for i in (8, 4, 0)
]
MOCK_CANDIDATE_DATASETS_ECOSYSTEM_CONVERSION = pd.DataFrame(_ordered)


@pytest.fixture(scope="function", autouse=True)
def mock_rag_candidate_datasets():
    """Mock rag_candidate_datasets to return MOCK_CANDIDATE_DATASETS_ECOSYSTEM_CONVERSION."""

    async def _return_mock_df(_query, k=3):
        return MOCK_CANDIDATE_DATASETS_ECOSYSTEM_CONVERSION.copy()

    with patch(
        "src.agent.tools.pick_dataset.rag_candidate_datasets",
        new_callable=AsyncMock,
        side_effect=_return_mock_df,
    ):
        yield


@pytest.fixture(scope="session", autouse=True)
def reset_google_clients():
    """Reset cached Google clients at session start to match active event loop."""
    llms_module = sys.modules["src.agent.llms"]
    pd_module = sys.modules["src.agent.tools.pick_dataset"]

    # Reset retriever cache so a fresh embeddings client is created
    pd_module.retriever_cache = None
    # Recreate SMALL_MODEL to get fresh client connections on the current event loop
    llms_module.SMALL_MODEL = llms_module.get_small_model()
    yield
    # Cleanup
    pd_module.retriever_cache = None


def has_insights(tool_steps: list[dict]) -> bool:
    for tool_step in tool_steps:
        if tool_step.get("insight_id"):
            return True
    return False


async def run_agent(query: str, thread_id: str | None = None):
    """Run the agent with a query and print output at each step."""

    if thread_id is None:
        thread_id = str(uuid.uuid4())

    print(f"🚀 Starting agent with thread_id: {thread_id}")
    print(f"📝 Query: {query}")
    print("=" * 60)

    config = {"configurable": {"thread_id": thread_id}}

    steps = []

    # Fetch the agent instance
    zeno_agent = await fetch_zeno_anonymous()

    i = 0
    async for step in zeno_agent.astream(
        {"messages": [{"role": "user", "content": query}]}, config
    ):
        print(f"\n🔄 Step {i + 1}:")
        print("-" * 40)

        # Print the step data
        for key, value in step.items():
            print(f"📊 Node: {key}")

            if "messages" in value:
                for msg in value["messages"]:
                    if hasattr(msg, "content") and msg.content:
                        print(f"💬 Message: {msg.content}")
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        for tool_call in msg.tool_calls:
                            print(
                                f"🔧 Tool Call: {tool_call['name']} with args: {tool_call['args']}"
                            )

            # Print other relevant state changes
            for state_key in [
                "aoi_selection",
                "dataset",
                "raw_data",
                "insight_id",
                "insights",
                "charts_data",
            ]:
                if state_key in value and value[state_key]:
                    print(f"📈 {state_key}: {value[state_key]}")

            if "statistics" in value and value["statistics"]:
                for stat in value["statistics"]:
                    print(f"📈 Dataset name: {stat['dataset_name']}")
                    print(f"📈 Start date: {stat['start_date']}")
                    print(f"📈 End date: {stat['end_date']}")
                    print(f"📈 Source URL: {stat['source_url']}")
                    print(f"📈 Data: {len(stat['data'])} rows")
                    print(f"📈 AOI names: {stat['aoi_names']}")

        print("-" * 40)
        steps.append(step)
        i += 1

    print("\n✅ Agent execution completed!")
    return steps


async def test_agent_for_disturbance_alerts_for_brazil(structlog_context):
    query = "Compare ecosystem conversion in Para and Parana in Brazil in the last 5 months"
    steps = await run_agent(query)
    assert len(steps) > 0
    tool_steps = [dat["tools"] for dat in steps if "tools" in dat]
    assert has_insights(tool_steps), "No insights found"
