import sys
import uuid
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest
from langchain_google_genai import ChatGoogleGenerativeAI

from src.agent.graph import fetch_zeno_anonymous
from src.agent.tools.datasets_config import DATASETS
from src.agent.tools.pick_dataset import DatasetSelectionResult

pytestmark = pytest.mark.asyncio(loop_scope="module")


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
        if "Parana" in _place_name or "Paraná" in _place_name:
            print("Returning MOCK_AOI_QUERY_RESULTS_PARANA")
            return MOCK_AOI_QUERY_RESULTS_PARANA.copy()
        if "Para" in _place_name:
            print("Returning MOCK_AOI_QUERY_RESULTS_PARA_BRAZIL")
            return MOCK_AOI_QUERY_RESULTS_PARA_BRAZIL.copy()
        return MOCK_AOI_QUERY_RESULTS_PARA_BRAZIL.copy()

    with patch(
        "src.agent.tools.pick_aoi.query_aoi_database",
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
        "src.agent.tools.pick_aoi.query_subregion_database",
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

MOCK_AOI_QUERY_RESULTS_UNITED_STATES = pd.DataFrame(
    {
        "src_id": {
            0: "USA",
            1: "USA.5_1",
            2: "USA.9_1",
            3: "USA.44_1",
        },
        "name": {
            0: "United States",
            1: "California, United States",
            2: "Florida, United States",
            3: "Texas, United States",
        },
        "subtype": {
            0: "country",
            1: "state-province",
            2: "state-province",
            3: "state-province",
        },
        "source": {
            0: "gadm",
            1: "gadm",
            2: "gadm",
            3: "gadm",
        },
        "similarity_score": {
            0: 0.99,
            1: 0.72,
            2: 0.71,
            3: 0.7,
        },
    }
)

MOCK_US_STATES = pd.DataFrame(
    [
        {
            "name": f"State {i}, United States",
            "subtype": "state-province",
            "src_id": f"USA.{i}_1",
            "source": "gadm",
        }
        for i in range(1, 51)
    ]
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
    query = "Tell me the county with the highest tree cover loss in the United States"
    steps = await run_agent(query)
    assert len(steps) > 0
    tool_steps = [dat["tools"] for dat in steps if "tools" in dat]
    assert has_insights(tool_steps), "No insights found"


async def test_agent_tree_cover_loss_across_all_us_states_under_15_steps(
    structlog_context,
):
    query = "Show me tree cover loss across all states in the United States"
    tree_cover_loss = next(d for d in DATASETS if d["dataset_id"] == 4)
    selection_result = DatasetSelectionResult(
        dataset_id=tree_cover_loss["dataset_id"],
        dataset_name=tree_cover_loss["dataset_name"],
        context_layer=None,
        reason="Tree cover loss is the best dataset for comparing loss across U.S. states.",
        tile_url=tree_cover_loss["tile_url"],
        analytics_api_endpoint=tree_cover_loss["analytics_api_endpoint"],
        description=tree_cover_loss["description"],
        prompt_instructions=tree_cover_loss["prompt_instructions"],
        methodology=tree_cover_loss["methodology"],
        cautions=tree_cover_loss["cautions"],
        function_usage_notes=tree_cover_loss["function_usage_notes"],
        citation=tree_cover_loss["citation"],
        content_date=tree_cover_loss["content_date"],
        language="en",
        selection_hints=tree_cover_loss.get("selection_hints"),
        code_instructions=tree_cover_loss.get("code_instructions"),
        presentation_instructions=tree_cover_loss.get(
            "presentation_instructions"
        ),
    )

    async def _return_mock_us_aoi(_place_name, result_limit=10):
        if "United States" in _place_name or "USA" in _place_name:
            return MOCK_AOI_QUERY_RESULTS_UNITED_STATES.copy()
        return MOCK_AOI_QUERY_RESULTS_PARA_BRAZIL.copy()

    async def _return_mock_us_states(subregion_name, source, src_id):
        if (
            subregion_name == "state"
            and source == "gadm"
            and src_id == "USA"
        ):
            return MOCK_US_STATES.copy()
        return pd.DataFrame(
            [
                {
                    "name": f"Mock {subregion_name}",
                    "subtype": "district-county",
                    "src_id": src_id,
                    "source": source,
                }
            ]
        )

    with (
        patch(
            "src.agent.tools.pick_aoi.query_aoi_database",
            new_callable=AsyncMock,
            side_effect=_return_mock_us_aoi,
        ),
        patch(
            "src.agent.tools.pick_aoi.query_subregion_database",
            new_callable=AsyncMock,
            side_effect=_return_mock_us_states,
        ),
        patch(
            "src.agent.tools.pick_dataset.select_best_dataset",
            new_callable=AsyncMock,
            return_value=selection_result,
        ),
    ):
        steps = await run_agent(query)

    assert len(steps) < 15
