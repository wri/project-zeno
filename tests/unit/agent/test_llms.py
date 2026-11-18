"""Tests for the retry and fallback around model calls made outside the agent loop."""

import pytest
import structlog.testing
from google.genai.errors import ServerError
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel

from src.agent import llms
from src.agent.config import AgentSettings
from tests.fakes import ScriptedGemini


class _Pick(BaseModel):
    choice: str


class _ScriptedModel:
    """Stands in for a chat model: each call plays the next outcome in turn,
    raising it if it is an exception."""

    def __init__(self, *outcomes):
        self._outcomes = list(outcomes)
        self.calls = 0

    def with_structured_output(self, schema):
        async def _call(_input):
            self.calls += 1
            outcome = self._outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return schema(choice=outcome)

        return RunnableLambda(_call)


def _unavailable():
    """The 503 Gemini answers when it is briefly overloaded."""
    return ServerError(
        503,
        {
            "error": {
                "code": 503,
                "message": "This model is currently experiencing high demand.",
                "status": "UNAVAILABLE",
            }
        },
    )


@pytest.fixture(autouse=True)
def _no_retry_wait(monkeypatch):
    monkeypatch.setattr(
        llms, "RETRY_WAIT", {"initial": 0, "max": 0, "jitter": 0}
    )


def _use_models(monkeypatch, small, *fallbacks):
    monkeypatch.setattr(llms, "SMALL_MODEL", small)
    monkeypatch.setattr(llms, "SMALL_FALLBACK_MODELS", list(fallbacks))


@pytest.mark.asyncio
async def test_a_transient_503_is_retried_on_the_same_model(monkeypatch):
    small = _ScriptedModel(_unavailable(), "small")
    fallback = _ScriptedModel("fallback")
    _use_models(monkeypatch, small, fallback)

    result = await llms.resilient_structured_output(_Pick).ainvoke("q")

    assert result == _Pick(choice="small")
    assert small.calls == 2
    assert fallback.calls == 0


@pytest.mark.asyncio
async def test_persistent_503s_fall_back_to_the_next_model(monkeypatch):
    small = _ScriptedModel(*[_unavailable()] * llms.RETRY_ATTEMPTS)
    fallback = _ScriptedModel("fallback")
    _use_models(monkeypatch, small, fallback)

    result = await llms.resilient_structured_output(_Pick).ainvoke("q")

    assert result == _Pick(choice="fallback")
    assert small.calls == llms.RETRY_ATTEMPTS


@pytest.mark.asyncio
async def test_a_non_transient_error_falls_back_without_a_retry(monkeypatch):
    small = _ScriptedModel(ValueError("400 INVALID_ARGUMENT"))
    fallback = _ScriptedModel("fallback")
    _use_models(monkeypatch, small, fallback)

    result = await llms.resilient_structured_output(_Pick).ainvoke("q")

    assert result == _Pick(choice="fallback")
    assert small.calls == 1


@pytest.mark.asyncio
async def test_the_error_surfaces_once_every_model_has_failed(monkeypatch):
    small = _ScriptedModel(*[_unavailable()] * llms.RETRY_ATTEMPTS)
    fallback = _ScriptedModel(*[_unavailable()] * llms.RETRY_ATTEMPTS)
    _use_models(monkeypatch, small, fallback)

    with pytest.raises(ServerError):
        await llms.resilient_structured_output(_Pick).ainvoke("q")

    assert fallback.calls == llms.RETRY_ATTEMPTS


@pytest.mark.asyncio
async def test_a_model_passed_in_is_retried_but_used_alone(monkeypatch):
    small = _ScriptedModel("small")
    _use_models(monkeypatch, small, _ScriptedModel("fallback"))
    own = _ScriptedModel(_unavailable(), ValueError("still broken"))

    with pytest.raises(ValueError):
        await llms.resilient_structured_output(_Pick, own).ainvoke("q")

    assert own.calls == 2
    assert small.calls == 0


def test_small_fallbacks_skip_the_small_model_itself(monkeypatch):
    monkeypatch.setattr(AgentSettings, "small_model", "gemini-flash")
    monkeypatch.setattr(
        AgentSettings,
        "small_fallback_models",
        "gemini-flash, gemini-flash-lite",
    )

    assert llms.get_small_fallback_models() == [llms.GEMINI_FLASH_LITE]


def test_an_unknown_small_fallback_is_rejected(monkeypatch):
    monkeypatch.setattr(AgentSettings, "small_fallback_models", "gemini-ultra")

    with pytest.raises(ValueError, match="gemini-ultra"):
        llms.get_small_fallback_models()


# --- resilient_json_output --------------------------------------------------
#
# Same policy as resilient_structured_output, but the reply is requested as
# JSON through the mime type (no response schema) and validated here.


def _reply(choice: str) -> str:
    return f'{{"choice": "{choice}"}}'


@pytest.mark.asyncio
async def test_json_output_requests_the_mime_type_and_no_schema(monkeypatch):
    small = ScriptedGemini(_reply("small"))
    _use_models(monkeypatch, small)

    result = await llms.resilient_json_output(_Pick).ainvoke("q")

    assert result == _Pick(choice="small")
    _, kwargs = small.calls[0]
    assert kwargs == {"response_mime_type": "application/json"}


@pytest.mark.asyncio
async def test_json_output_retries_a_transient_503_on_the_same_model(
    monkeypatch,
):
    small = ScriptedGemini(_unavailable(), _reply("small"))
    fallback = ScriptedGemini(_reply("fallback"))
    _use_models(monkeypatch, small, fallback)

    result = await llms.resilient_json_output(_Pick).ainvoke("q")

    assert result == _Pick(choice="small")
    assert (len(small.calls), len(fallback.calls)) == (2, 0)


@pytest.mark.asyncio
async def test_json_output_falls_back_after_persistent_503s(monkeypatch):
    small = ScriptedGemini(*[_unavailable()] * llms.RETRY_ATTEMPTS)
    fallback = ScriptedGemini(_reply("fallback"))
    _use_models(monkeypatch, small, fallback)

    result = await llms.resilient_json_output(_Pick).ainvoke("q")

    assert result == _Pick(choice="fallback")
    assert len(small.calls) == llms.RETRY_ATTEMPTS


@pytest.mark.asyncio
async def test_json_output_falls_back_without_a_retry_on_other_errors(
    monkeypatch,
):
    small = ScriptedGemini(ValueError("400 INVALID_ARGUMENT"))
    fallback = ScriptedGemini(_reply("fallback"))
    _use_models(monkeypatch, small, fallback)

    result = await llms.resilient_json_output(_Pick).ainvoke("q")

    assert result == _Pick(choice="fallback")
    assert len(small.calls) == 1


@pytest.mark.asyncio
async def test_json_output_retries_a_malformed_reply_once(monkeypatch):
    small = ScriptedGemini("Sure! Here you go", _reply("small"))
    fallback = ScriptedGemini(_reply("fallback"))
    _use_models(monkeypatch, small, fallback)

    result = await llms.resilient_json_output(_Pick).ainvoke("q")

    assert result == _Pick(choice="small")
    assert (len(small.calls), len(fallback.calls)) == (2, 0)


@pytest.mark.asyncio
async def test_json_output_falls_back_when_replies_stay_malformed(monkeypatch):
    small = ScriptedGemini("nope", "still nope")
    fallback = ScriptedGemini(_reply("fallback"))
    _use_models(monkeypatch, small, fallback)

    result = await llms.resilient_json_output(_Pick).ainvoke("q")

    assert result == _Pick(choice="fallback")
    assert len(small.calls) == 2


@pytest.mark.asyncio
async def test_json_output_accepts_a_reply_in_a_code_fence(monkeypatch):
    small = ScriptedGemini(f"```json\n{_reply('small')}\n```")
    _use_models(monkeypatch, small)

    result = await llms.resilient_json_output(_Pick).ainvoke("q")

    assert result == _Pick(choice="small")


@pytest.mark.asyncio
async def test_json_output_uses_a_model_passed_in_alone(monkeypatch):
    small = ScriptedGemini(_reply("small"))
    _use_models(monkeypatch, small, ScriptedGemini(_reply("fallback")))
    own = ScriptedGemini(_unavailable(), ValueError("still broken"))

    with pytest.raises(ValueError):
        await llms.resilient_json_output(_Pick, own).ainvoke("q")

    assert (len(own.calls), len(small.calls)) == (2, 0)


@pytest.mark.asyncio
async def test_json_output_keeps_structured_output_for_other_providers(
    monkeypatch,
):
    # The JSON mime type is a Gemini parameter; any other model keeps the
    # provider's own structured output, with the same retry.
    other = _ScriptedModel(_unavailable(), "other")
    _use_models(monkeypatch, other)

    result = await llms.resilient_json_output(_Pick).ainvoke("q")

    assert result == _Pick(choice="other")
    assert other.calls == 2


@pytest.mark.asyncio
async def test_a_final_failure_logs_one_event_naming_the_cause(monkeypatch):
    small = ScriptedGemini(*[_unavailable()] * llms.RETRY_ATTEMPTS)
    fallback = ScriptedGemini(*[_unavailable()] * llms.RETRY_ATTEMPTS)
    _use_models(monkeypatch, small, fallback)

    with structlog.testing.capture_logs() as logs:
        with pytest.raises(ServerError):
            await llms.resilient_json_output(_Pick).ainvoke("q")

    failed = [
        log for log in logs if log["event"] == "structured_output_failed"
    ]
    assert len(failed) == 1
    assert failed[0]["log_level"] == "error"
    assert failed[0]["schema"] == "_Pick"
    assert failed[0]["error_type"] == "server"


@pytest.mark.asyncio
async def test_a_reply_that_never_parses_is_reported_as_a_format_failure(
    monkeypatch,
):
    _use_models(monkeypatch, ScriptedGemini("nope", "nope again"))

    with structlog.testing.capture_logs() as logs:
        with pytest.raises(llms.StructuredOutputFormatError):
            await llms.resilient_json_output(_Pick).ainvoke("q")

    failed = [
        log for log in logs if log["event"] == "structured_output_failed"
    ]
    assert [log["error_type"] for log in failed] == ["format"]


@pytest.mark.asyncio
async def test_success_logs_no_failure_event(monkeypatch):
    _use_models(monkeypatch, ScriptedGemini(_unavailable(), _reply("small")))

    with structlog.testing.capture_logs() as logs:
        await llms.resilient_json_output(_Pick).ainvoke("q")

    assert not [
        log for log in logs if log["event"] == "structured_output_failed"
    ]


@pytest.mark.asyncio
async def test_format_errors_log_where_and_how_but_never_the_reply(
    monkeypatch,
):
    reply = '{"choice": 5, "note": "Piauí lost 3,600 ha"}'
    _use_models(monkeypatch, ScriptedGemini(reply, _reply("ok")))

    with structlog.testing.capture_logs() as logs:
        await llms.resilient_json_output(_Pick).ainvoke("q")

    [entry] = [
        log for log in logs if log["event"] == "structured_output_format_error"
    ]
    assert entry["log_level"] == "warning"
    assert entry["schema"] == "_Pick"
    assert entry["model"] == "scripted-gemini"
    assert entry["errors"] == [{"loc": "choice", "type": "string_type"}]
    assert entry["length"] == len(reply)
    assert "Piauí" not in repr(logs)


@pytest.mark.asyncio
async def test_unparseable_text_is_reported_at_the_root(monkeypatch):
    _use_models(monkeypatch, ScriptedGemini("not json", _reply("ok")))

    with structlog.testing.capture_logs() as logs:
        await llms.resilient_json_output(_Pick).ainvoke("q")

    [entry] = [
        log for log in logs if log["event"] == "structured_output_format_error"
    ]
    assert entry["errors"] == [{"loc": "(root)", "type": "json_invalid"}]


# --- json_reply_instruction ---------------------------------------------------


class _Pair(BaseModel):
    summary: str
    ideas: list[str]


class _Mixed(BaseModel):
    name: str
    count: int
    ratio: float
    ok: bool
    tags: list[str]
    sizes: list[int]


class _Nested(BaseModel):
    inner: _Pick


class _Optional(BaseModel):
    note: str | None = None


def test_instruction_for_one_field():
    assert llms.json_reply_instruction(_Pick) == (
        "Reply with a single JSON object and nothing else, with exactly "
        'these keys: "choice" (a string). Do not wrap it in code fences.'
    )


def test_instruction_for_two_fields_is_the_wording_we_measured():
    # This exact text produced 0 corrupted replies in 300 probe runs.
    assert llms.json_reply_instruction(_Pair) == (
        "Reply with a single JSON object and nothing else, with exactly "
        'these keys: "summary" (a string) and "ideas" (an array of strings). '
        "Do not wrap it in code fences."
    )


def test_instruction_for_many_fields():
    assert llms.json_reply_instruction(_Mixed) == (
        "Reply with a single JSON object and nothing else, with exactly "
        'these keys: "name" (a string), "count" (an integer), "ratio" (a '
        'number), "ok" (a boolean), "tags" (an array of strings) and "sizes" '
        "(an array of integers). Do not wrap it in code fences."
    )


@pytest.mark.parametrize("schema", [_Nested, _Optional])
def test_instruction_refuses_shapes_it_has_not_been_checked_for(schema):
    with pytest.raises(TypeError, match=schema.__name__):
        llms.json_reply_instruction(schema)
