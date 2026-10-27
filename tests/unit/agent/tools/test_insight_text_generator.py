"""Unit tests for InsightTextGenerator.

The LLM chain is replaced with a fake runnable so these are hermetic; they
assert the prompt is grounded in chart data + dataset cautions/presentation and
honors the wording guide.
"""

import pytest
import structlog.testing

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
async def test_generate_passes_executor_context(generator):
    gen, fake = generator
    context = "High total: 1306617.82 ha\nHighest total: 12982.53 ha"
    await gen.generate(
        CHARTS, DATASET, query="Loss?", executor_context=context
    )
    assert fake.last_inputs["executor_context"] == context


@pytest.mark.asyncio
async def test_generate_defaults_executor_context(generator):
    gen, fake = generator
    await gen.generate(CHARTS, DATASET, query="Loss?")
    assert fake.last_inputs["executor_context"] == "(none)"


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


# --- non-ASCII words are kept out of the prompt ---------------------------


class _EchoChain(_FakeChain):
    """Answers with the sanitized stand-ins it was given, as a model that
    copies names from the prompt would."""

    async def ainvoke(self, inputs, config=None):
        self.last_inputs = inputs
        return InsightText(
            primary_insight="Piaui lost 3,600 ha; Sao Paulo lost 10 ha.",
            follow_up_suggestions=["Why did Piaui change?"],
        )


@pytest.mark.asyncio
async def test_non_ascii_words_are_sanitized_in_prompt_and_restored():
    gen = InsightTextGenerator.__new__(InsightTextGenerator)
    gen._chain = chain = _EchoChain()
    charts = [
        InsightChart(
            position=0,
            title="Perda de cobertura em Piauí",
            chart_type="bar",
            x_axis="year",
            y_axis="area_ha",
            chart_data=[{"year": 2020, "area_ha": 1.0}],
        )
    ]

    result = await gen.generate(
        charts,
        {"cautions": "Dados de São Paulo são estimativas."},
        query="Perda em Piauí",
        executor_context="Piauí: 3,600 ha",
    )

    sent = chain.last_inputs
    for field in ("query", "executor_context", "cautions", "charts"):
        assert sent[field].isascii(), field
    assert "Piaui" in sent["query"]
    assert "Sao Paulo" in sent["cautions"]
    assert (
        result.primary_insight == "Piauí lost 3,600 ha; São Paulo lost 10 ha."
    )
    assert result.follow_up_suggestions == ["Why did Piauí change?"]


@pytest.mark.asyncio
async def test_system_prompt_inputs_are_not_sanitized(generator):
    gen, fake = generator
    await gen.generate(CHARTS, DATASET, query="Perda em Piauí", language="pt")
    # The language name tells the model what to write in; it must stay intact.
    assert fake.last_inputs["language"] == "Português"


class _GlitchedChain(_FakeChain):
    """A model that writes control characters on its own, with no accented
    word in the prompt to blame (e.g. a Portuguese narrative)."""

    async def ainvoke(self, inputs, config=None):
        self.last_inputs = inputs
        return InsightText(
            primary_insight="A previs\x03o para o Piau\x00 melhorou.",
            follow_up_suggestions=["Compare com Maranh\x03o."],
        )


@pytest.mark.asyncio
async def test_control_characters_the_model_writes_itself_are_stripped():
    gen = InsightTextGenerator.__new__(InsightTextGenerator)
    gen._chain = _GlitchedChain()

    with structlog.testing.capture_logs() as logs:
        result = await gen.generate(
            CHARTS, DATASET, query="Loss?", language="pt"
        )

    assert result.primary_insight == "A previso para o Piau melhorou."
    assert result.follow_up_suggestions == ["Compare com Maranho."]
    # Stripping is logged, tagged with the field it happened in, so a rise in
    # model-written control characters shows up in the logs.
    stripped = [
        log for log in logs if log["event"] == "control_chars_stripped"
    ]
    assert [(log["log_level"], log["field"]) for log in stripped] == [
        ("warning", "text_stage.primary_insight"),
        ("warning", "text_stage.follow_up_suggestion"),
    ]
    assert all(log["count"] >= 1 and log["codepoints"] for log in stripped)
