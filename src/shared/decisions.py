"""A small client for the jev decision model (Typesafe), on OpenRouter.

A decision model does not write text. It gets a situation (the "state") and
a set of questions, each with a fixed set of options, and returns one option
for each question with a probability for each option. The endpoint is
OpenRouter's alpha decisions API (`/api/alpha/decisions`), not
chat/completions. Pin the model version (`DECISION_MODEL`): the endpoint and
the "latest" alias can change without notice.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Optional

import httpx

from src.shared.config import SharedSettings
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

# Upper bound for the options of one choice question. Kept well below what
# the API takes: more options than this means a pre-filter is missing.
MAX_OPTIONS = 255
# Statuses that a second attempt can fix (rate limit, overload).
_RETRY_STATUSES = {429, 500, 502, 503, 504}
_ATTEMPTS = 2


@dataclass
class Question:
    """One choice question: option key to the text the model reads."""

    instructions: str
    options: dict[str, str]


@dataclass
class Answer:
    choice: str
    probability: float
    probabilities: dict[str, float] = field(default_factory=dict)


class DecisionError(RuntimeError):
    """The decision model could not answer."""


def _payload(state: str, questions: dict[str, Question]) -> dict:
    return {
        "model": SharedSettings.decision_model,
        "state": state,
        "questions": {
            name: {
                "type": "choice",
                "instructions": q.instructions,
                "criteria": q.options,
            }
            for name, q in questions.items()
        },
    }


def _answers(body: dict, questions: dict[str, Question]) -> dict[str, Answer]:
    answers: dict[str, Answer] = {}
    for name, raw in (body.get("answers") or {}).items():
        choice = raw.get("choice")
        if name not in questions or choice not in questions[name].options:
            continue
        probabilities = raw.get("probabilities") or {}
        answers[name] = Answer(
            choice=choice,
            probability=probabilities.get(
                choice, raw.get("confidence") or 0.0
            ),
            probabilities=probabilities,
        )
    return answers


async def decide(
    state: str,
    questions: dict[str, Question],
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Answer]:
    """Ask all `questions` in one call; return the answer per question.

    A question with fewer than 2 options is not sent: the API rejects it.
    The caller decides what a missing answer means.

    Raises:
        DecisionError: When the key is missing or the call fails.
    """
    questions = {
        name: q for name, q in questions.items() if len(q.options) >= 2
    }
    if not questions:
        return {}
    for name, q in questions.items():
        if len(q.options) > MAX_OPTIONS:
            raise DecisionError(
                f"question {name!r} has {len(q.options)} options "
                f"(at most {MAX_OPTIONS})"
            )
    if not SharedSettings.openrouter_api_key:
        raise DecisionError("OPENROUTER_API_KEY is not set")

    headers = {"Authorization": f"Bearer {SharedSettings.openrouter_api_key}"}
    payload = _payload(state, questions)
    owned = client is None
    client = client or httpx.AsyncClient(
        timeout=SharedSettings.decisions_timeout_seconds
    )
    try:
        for attempt in range(1, _ATTEMPTS + 1):
            try:
                response = await client.post(
                    SharedSettings.decisions_url,
                    json=payload,
                    headers=headers,
                )
            except httpx.HTTPError as exc:
                if attempt < _ATTEMPTS:
                    logger.warning("decisions call failed, retrying: %r", exc)
                    continue
                raise DecisionError(f"decisions call failed: {exc!r}") from exc
            if response.status_code == 200:
                return _answers(response.json(), questions)
            if response.status_code in _RETRY_STATUSES and attempt < _ATTEMPTS:
                logger.warning(
                    "decisions call returned %s, retrying",
                    response.status_code,
                )
                await asyncio.sleep(0.5)
                continue
            raise DecisionError(
                f"decisions call failed ({response.status_code}): "
                f"{response.text}"
            )
    finally:
        if owned:
            await client.aclose()
    raise DecisionError("decisions call failed")  # not reached
