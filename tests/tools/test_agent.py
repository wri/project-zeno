import uuid

import pytest

from src.agents.agents import fetch_zeno_anonymous


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
def user():
    """Override the global user fixture to avoid database connections."""
    pass


@pytest.fixture(scope="function", autouse=True)
def user_ds():
    """Override the global user_ds fixture to avoid database connections."""
    pass


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


@pytest.mark.parametrize(
    "dataset_name, dataset_year",
    [
        ("ecosystem disturbance alerts", 2024),
        ("land cover change", 2024),
        ("grasslands", 2022),
        ("natural lands", 2020),
        ("tree cover loss", 2024),
    ],
)
@pytest.mark.asyncio
async def test_full_agent_for_datasets(
    structlog_context, dataset_name, dataset_year
):
    query = f"What are the trends of {dataset_name} in Pima County, Arizona for July {dataset_year}?"

    steps = await run_agent(query)

    assert len(steps) > 0

    has_raw_data = False
    has_insights = False

    for tool_step in [dat["tools"] for dat in steps if "tools" in dat]:
        if tool_step.get("insight_count", 0) > 0:
            has_insights = True
        if "raw_data" in tool_step:
            if len(next(iter(tool_step["raw_data"].values()))["value"]) > 0:
                has_raw_data = True

    assert has_insights
    assert has_raw_data


@pytest.mark.asyncio
async def test_agent_for_disturbance_alerts_in_brazil(structlog_context):
    query = "Tell me what is happening with ecosystem conversion in Para, Brazil in the last 8 months"

    steps = await run_agent(query)

    assert len(steps) > 0

    has_raw_data = False

    for tool_step in [dat["tools"] for dat in steps if "tools" in dat]:
        if "raw_data" in tool_step:
            if len(next(iter(tool_step["raw_data"].values()))["value"]) > 0:
                has_raw_data = True

    assert has_raw_data


@pytest.mark.asyncio
async def test_agent_disturbance_alerts_with_comparison(structlog_context):
    query = "Compare dist alerts in Para and Mato Grosso, Brazil in the last 8 months."

    steps = await run_agent(query)

    assert len(steps) > 0

    has_raw_data = False

    for tool_step in [dat["tools"] for dat in steps if "tools" in dat]:
        if "raw_data" in tool_step:
            if len(next(iter(tool_step["raw_data"].values()))["name"]) > 0:
                has_raw_data = True
        if "charts_data" in tool_step:
            assert "Mato Grosso" in tool_step["charts_data"][0]["title"]
            assert "Pará" in tool_step["charts_data"][0]["title"]

    assert has_raw_data
