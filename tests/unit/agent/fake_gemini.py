"""Gemini test doubles that keep the production request-building path.

Both are real `ChatGoogleGenerativeAI` subclasses, so everything up to the
network call (including `_prepare_request`, which turns the bound kwargs
into the API request) is the library's own code.
"""

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import PrivateAttr

_MODEL = "gemini-3-flash-preview"


class StopBeforeNetwork(Exception):
    """Raised by RequestSpyGemini once the request has been built."""


class RequestSpyGemini(ChatGoogleGenerativeAI):
    """Records each request it would send, then stops before sending it."""

    _requests: list = PrivateAttr(default_factory=list)

    @classmethod
    def create(cls) -> "RequestSpyGemini":
        return cls(model=_MODEL, api_key="test-key", max_retries=0)

    @property
    def requests(self) -> list[dict]:
        return self._requests

    def _prepare_request(self, messages, **kwargs):
        request = super()._prepare_request(messages, **kwargs)
        self._requests.append(request)
        raise StopBeforeNetwork


class ScriptedGemini(ChatGoogleGenerativeAI):
    """Replays scripted outcomes, one per call.

    An outcome is an exception (raised), a reply string, or a callable that
    takes the messages and returns the reply string. The request is still
    built first, so a bad request fails here as it would in production.
    """

    _outcomes: list = PrivateAttr(default_factory=list)
    _calls: int = PrivateAttr(default=0)

    @classmethod
    def create(cls, *outcomes) -> "ScriptedGemini":
        model = cls(model=_MODEL, api_key="test-key", max_retries=0)
        model._outcomes = list(outcomes)
        return model

    @property
    def calls(self) -> int:
        return self._calls

    def _reply(self, messages, stop, kwargs) -> ChatResult:
        self._prepare_request(messages, stop=stop, **kwargs)
        self._calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        text = outcome(messages) if callable(outcome) else outcome
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=text))]
        )

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._reply(messages, stop, kwargs)

    async def _agenerate(
        self, messages, stop=None, run_manager=None, **kwargs
    ):
        return self._reply(messages, stop, kwargs)
