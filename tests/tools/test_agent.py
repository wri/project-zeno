import uuid

import pytest

from src.agent.graph import fetch_zeno_anonymous


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


def has_raw_data(tool_steps: list[dict]) -> bool:
    for tool_step in tool_steps:
        if "raw_data" not in tool_step:
            continue
        if not len(tool_step["raw_data"]):
            continue
        dat_by_aoi = list(tool_step["raw_data"].values())[0]
        dat = list(dat_by_aoi.values())[0]
        if "country" in dat and dat["country"] and len(dat["country"]) > 0:
            return True
        elif "aoi_id" in dat and dat["aoi_id"] and len(dat["aoi_id"]) > 0:
            return True
        elif "value" in dat and dat["value"] and len(dat["value"]) > 0:
            return True
        elif (
            "aoi_type" in dat and dat["aoi_type"] and len(dat["aoi_type"]) > 0
        ):
            return True
    return False


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


@pytest.mark.parametrize(
    "dataset_name, dataset_year",
    [
        ("trend of ecosystem disturbance alerts", 2024),
        ("trend of land cover change", 2024),
        ("land cover composition", 2024),
        ("trend of grasslands", 2022),
        ("distribution of natural lands", 2020),
        ("trend of tree cover loss", 2023),
        ("trend of tree cover gain", "2000-2020"),
        ("trend of forest greenhouse gas net flux", 2023),
        ("trend of tree cover", 2010),
        ("trend of tree cover by driver", 2020),
    ],
)
@pytest.mark.asyncio
async def test_full_agent_for_datasets(
    structlog_context, dataset_name, dataset_year
):
    query = f"What is the {dataset_name} in Para Brazil for {dataset_year}?"

    steps = await run_agent(query)

    assert len(steps) > 0

    tool_steps = [dat["tools"] for dat in steps if "tools" in dat]

    assert has_raw_data(tool_steps)

    assert has_insights(tool_steps), "No insights found"


@pytest.mark.asyncio
async def test_agent_for_disturbance_alerts_in_brazil(structlog_context):
    # query = "Tell me what is happening with ecosystem conversion in Para, Brazil in the last 8 months"
    # query = "land cover change in philipines in the past 5 years"
    # query = "how much forest does bolivia have?"
    # query = "tree cover loss in bolivia in past 4 years?"
    query = "Which country had the most distrubed area in November 2023, Australia or Brazil?"
    # query = "For mato grosso in Brazil, which municipality had the highest soy-linked deforestation emissions?"
    # query = (
    #     "What were the top three causes of deforestation in Brazil last year?"
    # )
    steps = await run_agent(query)

    assert len(steps) > 0

    tool_steps = [dat["tools"] for dat in steps if "tools" in dat]

    assert has_raw_data(tool_steps)


@pytest.mark.asyncio
async def test_agent_disturbance_alerts_with_comparison(structlog_context):
    query = "Compare dist alerts in Para and Mato Grosso, Brazil in the last 8 months."

    steps = await run_agent(query)

    assert len(steps) > 0

    tool_steps = [dat["tools"] for dat in steps if "tools" in dat]

    assert has_raw_data(tool_steps)


@pytest.mark.asyncio
async def test_agent_disturbance_alerts_with_comparison_and_subregion(
    structlog_context,
):
    query = "Compare dist alerts in kba's in Para and Mato Grosso, Brazil in the last 8 months."

    steps = await run_agent(query)

    assert len(steps) > 0

    tool_steps = [dat["tools"] for dat in steps if "tools" in dat]

    assert has_raw_data(tool_steps)


@pytest.mark.asyncio
async def test_agent_tc_gain_date_range_adjustment(structlog_context):
    query = "Analyze tree cover gain from 2015 to 2020 in Sweden."

    steps = await run_agent(query)

    assert len(steps) > 0

    tool_steps = [dat["tools"] for dat in steps if "tools" in dat]

    assert has_raw_data(tool_steps)

    assert has_insights(tool_steps), "No insights found"


@pytest.mark.asyncio
async def test_agent_tc_gain_date_range_clarification(structlog_context):
    query = "Analyze tree cover gain in 1990 in Sweden."

    steps = await run_agent(query)

    assert len(steps) > 0

    tool_steps = [dat["tools"] for dat in steps if "tools" in dat]

    assert not has_raw_data(tool_steps)


@pytest.mark.asyncio
async def test_agent_for_global_data_requests(structlog_context):
    query = "What are the top 3 places in Africa in 2020 with the most tree cover loss?"
    steps = await run_agent(query)

    assert len(steps) > 0

    tool_steps = [dat["tools"] for dat in steps if "tools" in dat]

    assert not tool_steps


@pytest.mark.asyncio
async def test_agent_for_commodities_dataset(structlog_context):
    query = "Show data for emission factors for Arabica Coffee in Parana, Brazil from 2020 to 2024"
    steps = await run_agent(query)

    assert len(steps) > 0

    tool_steps = [dat["tools"] for dat in steps if "tools" in dat]

    assert has_raw_data(tool_steps)
