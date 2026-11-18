"""The generate_insights tool message is short: no dataset cautions (they
are in the pick_dataset message) and no follow-up suggestions (the insight
card shows them)."""

from src.agent.subagents.analyst.charts.model import Insight
from src.agent.subagents.analyst.tool import _build_tool_message

INSIGHT = Insight(
    charts=[],
    primary_insight="Loss fell by half.",
    follow_up_suggestions=["Compare with 2020", "Show drivers"],
)


async def test_message_leaves_out_the_follow_ups():
    message = await _build_tool_message(INSIGHT)
    assert "Loss fell by half." in message
    assert "Compare with 2020" not in message
