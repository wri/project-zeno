"""Integration test: feature-flag profiles are loaded and respected."""

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from src.agent.agent_config import (
    DEFAULT_PROFILE,
    AgentConfig,
    AgentConfigRegistry,
)
from src.agent.graph import fetch_zeno


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cat_profile_responds_with_only_cat():
    """A profile with a custom system prompt and no tools should make the
    agent respond with only the word 'cat'."""
    registry = AgentConfigRegistry()
    registry.register(AgentConfig(DEFAULT_PROFILE))
    registry.register(
        AgentConfig(
            "cat",
            system_prompt=(
                "Say only the word 'cat' in response to everything. "
                "Do not say anything else."
            ),
        )
    )

    agent = await fetch_zeno(
        ff="cat",
        registry=registry,
        checkpointer=InMemorySaver(),
    )

    result = await agent.ainvoke(
        {
            "messages": [
                {"role": "user", "content": "What is the capital of France?"}
            ]
        },
        config={"configurable": {"thread_id": "test-cat"}},
    )

    last_message = result["messages"][-1].content
    if isinstance(last_message, list):
        last_message = " ".join(
            p.get("text", "") for p in last_message if isinstance(p, dict)
        )

    assert "cat" in last_message.lower()
