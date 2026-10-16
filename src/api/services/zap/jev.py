"""A small client for the jev decision model.

jev does not write text. It gets a situation and a set of questions, each
with a fixed list of options, and returns one option for each question with a
probability for each option. Ported from stac-zap (`src/zap/decide.ts`).
"""

from dataclasses import dataclass, field
from typing import Optional

import httpx

from src.api.config import APISettings

# Tells jev what the app is, so it reads indirect requests ("deforestation",
# "fires last year") as changes to the map.
CONTEXT = (
    "The user explores environmental data on a map with short, informal "
    "requests. The map shows one dataset and one area, and can chart the "
    "dataset for the area. Act on what the user means, not only on the "
    "words: a question about a topic asks for the dataset that measures it, "
    "and one request can change more than one thing."
)


@dataclass
class Question:
    """One choice question: option id to the text jev reads."""

    instructions: str
    options: dict[str, str]


@dataclass
class Answer:
    choice: str
    probability: float
    probabilities: dict[str, float] = field(default_factory=dict)


class JevError(RuntimeError):
    """jev could not answer."""


def build_state(prompt: str, current: dict[str, str], today: str) -> str:
    lines = "\n".join(
        f"- {label}: {value}" for label, value in current.items()
    )
    return (
        f"{CONTEXT}\n\nToday is {today}.\n\nUser request: {prompt}\n\n"
        f"Current map:\n{lines}"
    )


async def decide(
    state: str,
    questions: dict[str, Question],
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Answer]:
    """Ask jev all `questions` in one call; return the answer per question.

    Raises:
        JevError: When the key is missing or the call fails.
    """
    if not APISettings.openrouter_api_key:
        raise JevError("OPENROUTER_API_KEY is not set")
    payload = {
        "model": APISettings.jev_model,
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
    headers = {"Authorization": f"Bearer {APISettings.openrouter_api_key}"}
    owned = client is None
    client = client or httpx.AsyncClient(
        timeout=APISettings.jev_timeout_seconds
    )
    try:
        response = await client.post(
            APISettings.jev_url, json=payload, headers=headers
        )
    except httpx.HTTPError as exc:
        raise JevError(f"jev call failed: {exc}") from exc
    finally:
        if owned:
            await client.aclose()
    if response.status_code != 200:
        raise JevError(
            f"jev call failed ({response.status_code}): {response.text}"
        )

    answers: dict[str, Answer] = {}
    for name, raw in (response.json().get("answers") or {}).items():
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
