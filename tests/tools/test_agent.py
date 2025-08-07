import uuid

import pytest

from src.agents.agents import zeno_anonymous


# Override database fixtures to avoid database connections for these unit tests
@pytest.fixture(scope="function", autouse=True)
def test_db():
    """Override the global test_db fixture to avoid database connections."""
    pass


@pytest.fixture(scope="function", autouse=True)
def test_db_session():
    """Override the global test_db_session fixture to avoid database connections."""
    pass


def run_agent(query: str, thread_id: str | None = None):
    """Run the agent with a query and print output at each step."""

    if thread_id is None:
        thread_id = str(uuid.uuid4())

    print(f"🚀 Starting agent with thread_id: {thread_id}")
    print(f"📝 Query: {query}")
    print("=" * 60)

    config = {"configurable": {"thread_id": thread_id}}

    steps = []

    for i, step in enumerate(
        zeno_anonymous.stream(
            {"messages": [{"role": "user", "content": query}]}, config
        )
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

    print("\n✅ Agent execution completed!")
    return steps


def test_agent_natural_lands():
    query = "What is the distribution of natural lands in the canton of Bern, Switzerland?"
    steps = run_agent(query)
    assert len(steps) > 0
