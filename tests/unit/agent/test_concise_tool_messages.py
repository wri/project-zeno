"""The concise profile gets a shorter generate_insights message."""

from src.agent.subagents.analyst.charts.model import Insight
from src.agent.subagents.analyst.tool import _build_tool_message
from src.agent.tool_spec import (
    CONCISE_REPLIES,
    Availability,
    set_bound_availability,
)

INSIGHT = Insight(
    charts=[],
    primary_insight="Loss fell by half.",
    follow_up_suggestions=["Compare with 2020", "Show drivers"],
)


async def _message(flags: frozenset[str]) -> str:
    # Each async test runs in its own task, so the binding stays in the test.
    set_bound_availability(
        Availability(skills=frozenset(), tools=frozenset(), flags=flags)
    )
    return await _build_tool_message(INSIGHT, "Loss is not deforestation.")


async def test_default_message_has_cautions_and_follow_ups():
    message = await _message(frozenset())
    assert "Loss is not deforestation." in message
    assert "Compare with 2020" in message
    assert "Loss fell by half." in message


async def test_concise_message_leaves_out_cautions_and_follow_ups():
    message = await _message(frozenset({CONCISE_REPLIES}))
    assert "Loss fell by half." in message
    assert "Loss is not deforestation." not in message
    assert "Compare with 2020" not in message
