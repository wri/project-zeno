"""Integration test: feature-flag profiles are loaded and respected."""

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from src.agent.agent_config import (
    DEFAULT_PROFILE,
    AgentConfig,
    AgentConfigRegistry,
)
from src.agent.graph import fetch_zeno
from src.agent.subagents.pick_dataset.tool import SPEC as pick_dataset_spec


@pytest.mark.asyncio
async def test_cat_profile_responds_with_only_cat():
    """A profile with a custom system prompt and no tools should make the
    agent respond with only the word 'cat'."""
    registry = AgentConfigRegistry()
    registry.register(AgentConfig(DEFAULT_PROFILE, specs=()))
    registry.register(
        AgentConfig(
            "cat",
            specs=(),
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
    assert len(last_message.strip()) < 20  # only "cat", not a long response


@pytest.mark.asyncio
async def test_dataset_only_config_selects_dataset_without_other_tools():
    """An AgentConfig with only pick_dataset should select a dataset without
    calling pick_aoi, pull_data, or any other tool."""
    registry = AgentConfigRegistry()
    registry.register(AgentConfig(DEFAULT_PROFILE, specs=(pick_dataset_spec,)))

    agent = await fetch_zeno(
        registry=registry,
        checkpointer=InMemorySaver(),
    )

    result = await agent.ainvoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "tree cover loss in Brazil in 2015",
                }
            ]
        },
        config={"configurable": {"thread_id": "test-dataset-only"}},
    )

    tools_called = [
        tc["name"]
        for m in result["messages"]
        if hasattr(m, "tool_calls")
        for tc in (m.tool_calls or [])
    ]

    assert "pick_dataset" in tools_called
    assert "pick_aoi" not in tools_called
    assert "pull_data" not in tools_called
    assert result.get("dataset") is not None
