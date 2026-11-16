"""Test doubles shared by the tests that exercise model calls."""

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import Field


class ScriptedGemini(ChatGoogleGenerativeAI):
    """A real ``ChatGoogleGenerativeAI`` whose network call plays a script.

    Being the real class, it takes the same code path in
    ``resilient_json_output`` as production does (the JSON mime type is bound
    and the reply is parsed). Each call plays the next outcome:

    * an exception is raised, as a failed request would be;
    * a string is the model's reply;
    * a callable gets the prompt messages and returns the reply.

    With ``repeat=True`` a single outcome is played for every call. Every call
    is recorded in ``calls`` as ``(messages, kwargs)``.
    """

    outcomes: list = Field(default_factory=list)
    repeat: bool = False
    calls: list = Field(default_factory=list)

    def __init__(self, *outcomes, repeat: bool = False, **kwargs):
        super().__init__(
            model="gemini-3-flash-preview",
            api_key="unused",
            outcomes=list(outcomes),
            repeat=repeat,
            **kwargs,
        )

    def _play(self, messages, kwargs) -> ChatResult:
        self.calls.append((messages, kwargs))
        if self.repeat and len(self.outcomes) == 1:
            outcome = self.outcomes[0]
        else:
            outcome = self.outcomes.pop(0)
        if callable(outcome):
            outcome = outcome(messages)
        if isinstance(outcome, Exception):
            raise outcome
        reply = AIMessage(
            content=outcome,
            response_metadata={"model_name": "scripted-gemini"},
        )
        return ChatResult(generations=[ChatGeneration(message=reply)])

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._play(messages, kwargs)

    async def _agenerate(
        self, messages, stop=None, run_manager=None, **kwargs
    ):
        return self._play(messages, kwargs)


def prompt_text(messages) -> str:
    """The messages of one call as a single string."""
    return "\n".join(str(message.content) for message in messages)
