"""Unit tests for InsightTextGenerator.

The LLM chain is replaced with a fake runnable so these are hermetic; they
assert the prompt is grounded in chart data + dataset cautions/presentation and
honors the wording guide.
"""

import pytest

from src.agent.subagents.analyst.charts.model import InsightChart
from src.agent.subagents.analyst.text_generator import (
    InsightText,
    InsightTextGenerator,
)


class _FakeChain:
    """Captures inputs passed to ainvoke; returns a fixed InsightText."""

    def __init__(self):
        self.last_inputs = None
        self.last_config = None

    def with_config(self, **kwargs):
        return self

    async def ainvoke(self, inputs, config=None):
        self.last_inputs = inputs
        self.last_config = config
        return InsightText(
            primary_insight="Loss increased.",
            follow_up_suggestions=["Compare regions."],
        )


@pytest.fixture
def generator(monkeypatch):
    gen = InsightTextGenerator.__new__(InsightTextGenerator)
    fake = _FakeChain()
    gen._chain = fake
    return gen, fake


CHARTS = [
    InsightChart(
        position=0,
        title="Annual Loss",
        chart_type="bar",
        x_axis="year",
        y_axis="area_ha",
        chart_data=[{"year": 2020, "area_ha": 1234.5}],
    )
]
DATASET = {
    "cautions": "Tree cover loss is not deforestation.",
    "presentation_instructions": "Use neutral wording.",
}


@pytest.mark.asyncio
async def test_generate_returns_structured_text(generator):
    gen, _ = generator
    result = await gen.generate(CHARTS, DATASET, query="Loss in Brazil?")
    assert result.primary_insight == "Loss increased."
    assert result.follow_up_suggestions == ["Compare regions."]


@pytest.mark.asyncio
async def test_prompt_includes_cautions_and_presentation(generator):
    gen, fake = generator
    await gen.generate(CHARTS, DATASET, query="Loss in Brazil?")
    inputs = fake.last_inputs
    assert inputs["cautions"] == "Tree cover loss is not deforestation."
    assert inputs["presentation_instructions"] == "Use neutral wording."
    assert "Wording" in inputs["wording_guide"]


@pytest.mark.asyncio
async def test_prompt_serializes_chart_data(generator):
    gen, fake = generator
    await gen.generate(CHARTS, DATASET, query="Loss in Brazil?")
    charts_block = fake.last_inputs["charts"]
    assert "Annual Loss" in charts_block
    assert "year" in charts_block and "area_ha" in charts_block
    assert "1234.5" in charts_block
    # serialized as JSON, and the per-chart narrative field is excluded
    assert "chart_type" in charts_block
    assert "insight" not in charts_block


@pytest.mark.asyncio
async def test_config_is_forwarded_to_chain(generator):
    gen, fake = generator
    cfg = {"callbacks": ["x"]}
    await gen.generate(CHARTS, DATASET, query="q", config=cfg)
    assert fake.last_config == cfg
