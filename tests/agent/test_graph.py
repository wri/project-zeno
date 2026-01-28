import sys
import uuid
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest
from langchain_google_genai import ChatGoogleGenerativeAI

from src.agent.graph import fetch_zeno_anonymous
from src.agent.tools.datasets_config import DATASETS

# Use module-scoped event loop for all async tests in this module
# This prevents the "Event loop is closed" error when Google's gRPC clients
# cache their event loop reference across parameterized tests
pytestmark = pytest.mark.asyncio(loop_scope="module")


# Override database fixtures to avoid database connections for these unit tests
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


@pytest.fixture(scope="function", autouse=True)
def mock_query_aoi_database():
    """Mock query_aoi_database to return MOCK_AOI_QUERY_RESULTS_PARA_BRAZIL."""

    async def _return_mock_df(_place_name, result_limit=10):
        return MOCK_AOI_QUERY_RESULTS_PARA_BRAZIL.copy()

    with patch(
        "src.agent.tools.pick_aoi.query_aoi_database",
        new_callable=AsyncMock,
        side_effect=_return_mock_df,
    ):
        yield


MOCK_AOI_QUERY_RESULTS_PARA_BRAZIL = pd.DataFrame(
    {
        "src_id": [
            "BRA.16_1",
            "BRA.14_1",
            "BRA.15_1",
            "BRA.15.12_2",
            "BRA",
            "BRA.15.133_2",
            "BRA.16.266_2",
            "BRA.14.144_2",
            "BRA.16.183_2",
            "BRA.15.84_2",
        ],
        "name": [
            "Paraná, Brazil",
            "Pará, Brazil",
            "Paraíba, Brazil",
            "Arara, Paraíba, Brazil",
            "Brazil",
            "Parari, Paraíba, Brazil",
            "Piên, Paraná, Brazil",
            "Xinguara, Pará, Brazil",
            "Jussara, Paraná, Brazil",
            "Ibiara, Paraíba, Brazil",
        ],
        "subtype": [
            "state-province",
            "state-province",
            "state-province",
            "district-county",
            "country",
            "district-county",
            "district-county",
            "district-county",
            "district-county",
            "district-county",
        ],
        "source": ["gadm"] * 10,
        "similarity_score": [
            0.733333,
            0.714286,
            0.687500,
            0.631579,
            0.583333,
            0.578947,
            0.578947,
            0.571429,
            0.571429,
            0.571429,
        ],
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


@pytest.fixture(scope="module", autouse=True)
def reset_google_clients():
    """Reset cached Google clients at module start to use the correct event loop.

    Modules that did 'from src.agent.llms import SMALL_MODEL' at import time
    hold a reference to the old client; we must update those references too
    so they use the new client bound to this test module's event loop.

    IMPORTANT: We must create NEW model instances, not fetch from MODEL_REGISTRY,
    because the cached models have gRPC clients bound to the old event loop.
    """
    # Create fresh GEMINI_FLASH instance (used as SMALL_MODEL and in generate_insights)
    new_gemini_flash = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        temperature=0.3,
        max_tokens=None,
        include_thoughts=False,
        max_retries=2,
        thinking_budget=0,
        timeout=300,
    )

    # Update module-level references
    llms_module = sys.modules["src.agent.llms"]
    llms_module.SMALL_MODEL = new_gemini_flash
    llms_module.GEMINI_FLASH = new_gemini_flash

    pd_module = sys.modules.get("src.agent.tools.pick_dataset")
    if pd_module is not None:
        pd_module.retriever_cache = None
        pd_module.SMALL_MODEL = new_gemini_flash

    for module_name in (
        "src.agent.tools.pick_aoi",
        "src.agent.tools.data_handlers.analytics_handler",
    ):
        mod = sys.modules.get(module_name)
        if mod is not None and hasattr(mod, "SMALL_MODEL"):
            mod.SMALL_MODEL = new_gemini_flash

    # Reset GEMINI_FLASH in generate_insights module
    gi_module = sys.modules.get("src.agent.tools.generate_insights")
    if gi_module is not None:
        gi_module.GEMINI_FLASH = new_gemini_flash


def has_insights(tool_steps: list[dict]) -> bool:
    for tool_step in tool_steps:
        if len(tool_step.get("charts_data", [])) > 0:
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
                "aoi",
                "dataset",
                "raw_data",
                "insights",
                "charts_data",
            ]:
                if state_key in value and value[state_key]:
                    print(f"📈 {state_key}: {value[state_key]}")

        print("-" * 40)
        steps.append(step)
        i += 1

    print("\n✅ Agent execution completed!")
    return steps


async def test_agent_for_disturbance_alerts_for_brazil(structlog_context):
    query = "Tell me what is happening with ecosystem conversion in Para, Brazil in the last 8 months"
    steps = await run_agent(query)
    assert len(steps) > 0
    tool_steps = [dat["tools"] for dat in steps if "tools" in dat]
    assert has_insights(tool_steps), "No insights found"
