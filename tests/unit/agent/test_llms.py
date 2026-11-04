"""Tests for the retry and fallback around model calls made outside the agent loop."""

import pytest
from google.genai.errors import ServerError
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel

from src.agent import llms
from src.agent.config import AgentSettings


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
