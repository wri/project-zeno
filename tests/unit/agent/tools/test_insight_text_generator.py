"""Unit tests for InsightTextGenerator.

The LLM chain is replaced with a fake runnable so these are hermetic; they
assert the prompt is grounded in chart data + dataset cautions/presentation and
honors the wording guide.
"""

import pytest
import structlog.testing
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from pydantic import Field

from src.agent.subagents.analyst.charts.model import InsightChart
from src.agent.subagents.analyst.text_generator import (
    InsightText,
    InsightTextFormatError,
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


# --- how the answer is requested and parsed ------------------------------
#
# Gemini's schema-constrained decoding (`with_structured_output`) corrupts
# accented characters ("Piau\u0000"). The text stage therefore asks for JSON
# with the JSON mime type and no schema, and parses the reply itself.


class _ScriptedModel(FakeListChatModel):
    """Replies with the scripted texts in order and records every call."""

    calls: list = Field(default_factory=list)

    def _call(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append((messages, kwargs))
        return super()._call(messages, stop, run_manager, **kwargs)

    async def _acall(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append((messages, kwargs))
        return await super()._acall(messages, stop, run_manager, **kwargs)


GOOD_REPLY = (
    '{"primary_insight": "Piauí lost 3,600 ha.", '
    '"follow_up_suggestions": ["Compare Maranhão with Piauí."]}'
)


def _generator_for(*replies: str):
    model = _ScriptedModel(responses=list(replies))
    return InsightTextGenerator(model=model), model


@pytest.mark.asyncio
async def test_json_mime_type_is_requested_without_a_schema():
    gen, model = _generator_for(GOOD_REPLY)

    await gen.generate(CHARTS, DATASET, query="Loss?")

    _, kwargs = model.calls[0]
    assert kwargs == {"response_mime_type": "application/json"}


@pytest.mark.asyncio
async def test_prompt_asks_for_the_json_shape_in_the_requested_language():
    gen, model = _generator_for(GOOD_REPLY)

    await gen.generate(CHARTS, DATASET, query="Loss?", language="pt")

    system = model.calls[0][0][0].content
    assert "single JSON object" in system
    assert '"primary_insight"' in system
    assert '"follow_up_suggestions"' in system
    assert "Português" in system


@pytest.mark.asyncio
async def test_accented_text_survives_parsing():
    gen, _ = _generator_for(GOOD_REPLY)

    result = await gen.generate(CHARTS, DATASET, query="Loss?")

    assert result.primary_insight == "Piauí lost 3,600 ha."
    assert result.follow_up_suggestions == ["Compare Maranhão with Piauí."]


@pytest.mark.asyncio
async def test_code_fences_around_the_json_are_tolerated():
    gen, _ = _generator_for(f"```json\n{GOOD_REPLY}\n```")

    result = await gen.generate(CHARTS, DATASET, query="Loss?")

    assert result.primary_insight == "Piauí lost 3,600 ha."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_reply",
    [
        pytest.param("Piauí lost 3,600 ha.", id="not-json"),
        pytest.param('{"primary_insight": "Cut off', id="truncated"),
        pytest.param(
            '{"primary_insight": "No follow-ups."}', id="missing-key"
        ),
        pytest.param(
            '{"primary_insight": 5, "follow_up_suggestions": []}',
            id="wrong-type",
        ),
        pytest.param(
            '{"primary_insight": "  ", "follow_up_suggestions": []}',
            id="empty-insight",
        ),
    ],
)
async def test_a_malformed_reply_is_retried_once(bad_reply):
    gen, model = _generator_for(bad_reply, GOOD_REPLY)

    with structlog.testing.capture_logs() as logs:
        result = await gen.generate(CHARTS, DATASET, query="Loss?")

    assert result.primary_insight == "Piauí lost 3,600 ha."
    assert len(model.calls) == 2
    assert [
        log["log_level"]
        for log in logs
        if log["event"] == "insight_text_format_error"
    ] == ["warning"]


@pytest.mark.asyncio
async def test_two_malformed_replies_raise_instead_of_looping():
    gen, model = _generator_for("nope", "still nope", GOOD_REPLY)

    with pytest.raises(InsightTextFormatError):
        await gen.generate(CHARTS, DATASET, query="Loss?")

    assert len(model.calls) == 2


@pytest.mark.asyncio
async def test_the_real_gemini_request_has_the_mime_type_and_no_schema(
    monkeypatch,
):
    """What reaches the Gemini request config, not just what we bind."""
    from langchain_google_genai import ChatGoogleGenerativeAI

    seen = []
    original = ChatGoogleGenerativeAI._prepare_request

    def spy(self, *args, **kwargs):
        request = original(self, *args, **kwargs)
        seen.append(request["config"])
        raise RuntimeError("stop before any network call")

    monkeypatch.setattr(ChatGoogleGenerativeAI, "_prepare_request", spy)
    model = ChatGoogleGenerativeAI(
        model="gemini-3-flash-preview", api_key="unused", thinking_level="low"
    )

    with pytest.raises(RuntimeError, match="stop before"):
        await InsightTextGenerator(model=model).generate(
            CHARTS, DATASET, query="Loss?"
        )

    config = seen[0]
    assert config.response_mime_type == "application/json"
    assert config.response_schema is None
    assert config.response_json_schema is None


# --- control characters the model writes anyway ---------------------------


@pytest.mark.asyncio
async def test_language_name_reaches_the_prompt_intact(generator):
    gen, fake = generator
    await gen.generate(CHARTS, DATASET, query="Perda em Piauí", language="pt")
    # The language name tells the model what to write in.
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
