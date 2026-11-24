"""What InsightTextGenerator actually sends to Gemini, and gets back.

PZB-1243: the text stage asks for JSON by mime type, with no response
schema, so its system prompt has to spell out the keys itself.
"""

import unicodedata

import pytest
import structlog
from google.genai.errors import ServerError

from src.agent import llms
from src.agent.llms import json_reply_instruction
from src.agent.subagents.analyst.charts.model import InsightChart
from src.agent.subagents.analyst.text_generator import (
    InsightText,
    InsightTextGenerator,
)
from src.shared import text_sanitize
from tests.unit.agent.fake_gemini import (
    RequestSpyGemini,
    ScriptedGemini,
    StopBeforeNetwork,
)

CHARTS = [
    InsightChart(
        position=0,
        title="Annual loss",
        chart_type="bar",
        x_axis="year",
        y_axis="area_ha",
        chart_data=[{"year": 2020, "area_ha": 1234.5}],
    )
]
DATASET = {"cautions": "Tree cover loss is not deforestation."}


async def _captured_request(language="pt") -> dict:
    """Run the text stage against a spy and return the request it built."""
    model = RequestSpyGemini.create()
    with pytest.raises(StopBeforeNetwork):
        await InsightTextGenerator(model).generate(
            CHARTS, DATASET, "Loss in Piauí?", language=language
        )
    (request,) = model.requests
    return request


def _system_prompt(request: dict) -> str:
    parts = request["config"].system_instruction.parts
    return "".join(part.text for part in parts)


def _user_text(request: dict) -> str:
    return "".join(
        part.text for content in request["contents"] for part in content.parts
    )


@pytest.mark.asyncio
async def test_a_reply_round_trips_through_the_text_stage():
    model = ScriptedGemini.create(
        '{"primary_insight": "Piauí lost 5% of its cover.",'
        ' "follow_up_suggestions": ["Compare with Maranhão"]}'
    )

    result = await InsightTextGenerator(model).generate(
        CHARTS, DATASET, "Loss in Piauí?", language="pt"
    )

    assert result == InsightText(
        primary_insight="Piauí lost 5% of its cover.",
        follow_up_suggestions=["Compare with Maranhão"],
    )


@pytest.mark.asyncio
async def test_system_prompt_spells_out_the_json_keys_and_language():
    system = _system_prompt(await _captured_request(language="pt"))

    assert json_reply_instruction(InsightText) in system
    assert "Português" in system


@pytest.mark.asyncio
async def test_text_stage_sends_no_response_schema():
    config = (await _captured_request())["config"]

    assert config.response_mime_type == "application/json"
    assert config.response_schema is None
    assert config.response_json_schema is None


@pytest.mark.asyncio
async def test_the_place_name_reaches_the_model_unchanged():
    request = await _captured_request()

    assert "Loss in Piauí?" in _user_text(request)


def _glitching(escape: str, seen: list):
    """A reply that mimics the bug: every non-ASCII letter in the JSON reply
    becomes `escape`, a JSON escape for a control character. Records the
    messages it was sent in `seen`."""

    def reply(messages) -> str:
        seen.extend(messages)
        text = (
            '{"primary_insight": "Piauí and Maranhão lost cover.",'
            ' "follow_up_suggestions": ["Compare with Paraná"]}'
        )
        return "".join(c if c.isascii() else escape for c in text)

    return reply


@pytest.mark.parametrize("escape", [r"\u0000", r"\u0003"], ids=["NUL", "ETX"])
@pytest.mark.asyncio
async def test_a_glitching_model_gives_clean_text_and_sees_the_real_prompt(
    escape,
):
    seen = []
    model = ScriptedGemini.create(_glitching(escape, seen))

    result = await InsightTextGenerator(model).generate(
        CHARTS, DATASET, "Loss in Piauí?", language="pt"
    )

    texts = [result.primary_insight, *result.follow_up_suggestions]
    assert texts == [
        "Piau and Maranho lost cover.",
        "Compare with Paran",
    ]
    assert not any(unicodedata.category(c) == "Cc" for t in texts for c in t)
    sent = "".join(m.content for m in seen)
    assert "Loss in Piauí?" in sent
    assert "Português" in sent


class _ContextRecordingLogger:
    """Collect each warning with the structlog context bound when it was
    logged. merge_contextvars adds that context to every real log entry."""

    def __init__(self):
        self.warnings = []

    def warning(self, event, **fields):
        context = structlog.contextvars.get_contextvars()
        self.warnings.append((event, {**context, **fields}))

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


@pytest.mark.asyncio
async def test_control_chars_stripped_is_logged_with_the_language(
    monkeypatch,
):
    recorder = _ContextRecordingLogger()
    monkeypatch.setattr(text_sanitize, "logger", recorder)
    model = ScriptedGemini.create(_glitching(r"\u0000", []))

    await InsightTextGenerator(model).generate(
        CHARTS, DATASET, "Loss in Piauí?", language="pt"
    )

    stripped = [
        fields
        for event, fields in recorder.warnings
        if event == "control_chars_stripped"
    ]
    assert stripped
    assert all(fields["language"] == "pt" for fields in stripped)
    assert "language" not in structlog.contextvars.get_contextvars()


# --- The text stage keeps the shared retry and fallback policy -------------
# A hand-built chain in the text stage once lost both (see the PZB-1243
# notes). These fail if the text stage stops using resilient_json_output.

_REPLY = (
    '{"primary_insight": "Piauí lost 5% of its cover.",'
    ' "follow_up_suggestions": ["Compare with Maranhão"]}'
)


def _unavailable():
    """The 503 Gemini answers when it is briefly overloaded."""
    return ServerError(503, {"error": {"code": 503, "status": "UNAVAILABLE"}})


@pytest.fixture
def no_retry_wait(monkeypatch):
    monkeypatch.setattr(
        llms, "RETRY_WAIT", {"initial": 0, "max": 0, "jitter": 0}
    )


@pytest.mark.asyncio
async def test_the_text_stage_retries_a_transient_server_error(
    no_retry_wait,
):
    model = ScriptedGemini.create(_unavailable(), _REPLY)

    result = await InsightTextGenerator(model).generate(
        CHARTS, DATASET, "Loss in Piauí?", language="pt"
    )

    assert result.primary_insight == "Piauí lost 5% of its cover."
    assert model.calls == 2


@pytest.mark.asyncio
async def test_the_text_stage_falls_back_to_the_small_fallback_models(
    monkeypatch, no_retry_wait
):
    broken = ScriptedGemini.create(ValueError("not transient"))
    fallback = ScriptedGemini.create(_REPLY)
    monkeypatch.setattr(llms, "SMALL_MODEL", broken)
    monkeypatch.setattr(llms, "SMALL_FALLBACK_MODELS", [fallback])

    result = await InsightTextGenerator().generate(
        CHARTS, DATASET, "Loss in Piauí?", language="pt"
    )

    assert result.primary_insight == "Piauí lost 5% of its cover."
    assert (broken.calls, fallback.calls) == (1, 1)
