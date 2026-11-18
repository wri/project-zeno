"""The generate_insights tool message has the dataset cautions (the dataset
can come from a UI selection, with no pick_dataset message in the thread)
and no follow-up suggestions (the insight card shows them)."""

from src.agent.datasets.config import DATASETS
from src.agent.subagents.analyst.charts.model import Insight
from src.agent.subagents.analyst.tool import (
    _build_tool_message,
    _catalog_cautions,
)

INSIGHT = Insight(
    charts=[],
    primary_insight="Loss fell by half.",
    follow_up_suggestions=["Compare with 2020", "Show drivers"],
)


async def test_message_leaves_out_the_follow_ups():
    message = await _build_tool_message(INSIGHT)
    assert "Loss fell by half." in message
    assert "Compare with 2020" not in message


async def test_message_has_the_dataset_cautions():
    message = await _build_tool_message(INSIGHT, "Loss is not deforestation.")
    assert "Dataset cautions:" in message
    assert message.endswith("Loss is not deforestation.")


async def test_message_without_cautions_has_no_header():
    message = await _build_tool_message(INSIGHT, None)
    assert "Dataset cautions" not in message


def test_catalog_cautions_come_from_the_catalog():
    entry = next(d for d in DATASETS if d.get("cautions"))
    assert _catalog_cautions(entry["dataset_id"]) == entry["cautions"]
    assert _catalog_cautions(None) is None
