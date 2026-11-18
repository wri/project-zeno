"""The decisions client: request shape per provider, answer parsing, retries."""

import json

import httpx
import pytest

from src.shared import decisions
from src.shared.config import SharedSettings
from src.shared.decisions import DecisionError, Question, decide

QUESTIONS = {
    "topic": Question("Which topic?", {"fire": "Fires", "loss": "Loss"}),
}


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    monkeypatch.setattr(SharedSettings, "decision_provider", "jev")
    monkeypatch.setattr(SharedSettings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(SharedSettings, "google_api_key", "google-key")


def _ok(choice="fire"):
    return httpx.Response(
        200,
        json={
            "answers": {
                "topic": {
                    "type": "choice",
                    "choice": choice,
                    "probabilities": {"fire": 0.8, "loss": 0.2},
                    "confidence": 0.8,
                }
            }
        },
    )


def _client(*responses):
    """A client that returns `responses` in order and records requests."""
    requests = []
    queue = list(responses)

    def handler(request):
        requests.append(request)
        return queue.pop(0)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), requests


async def test_sends_choice_questions_and_reads_the_answers():
    client, requests = _client(
        httpx.Response(
            200,
            json={
                "answers": {
                    "topic": {
                        "type": "choice",
                        "choice": "fire",
                        "probabilities": {"fire": 0.8, "loss": 0.2},
                        "confidence": 0.8,
                    }
                }
            },
        )
    )

    answers = await decide("fires in Brazil", QUESTIONS, client=client)

    assert answers["topic"].choice == "fire"
    assert answers["topic"].probability == 0.8
    assert answers["topic"].probabilities == {"fire": 0.8, "loss": 0.2}
    (request,) = requests
    assert str(request.url) == SharedSettings.decisions_url
    assert request.headers["authorization"] == "Bearer test-key"
    assert json.loads(request.content) == {
        "model": "typesafe/jev-1.13",
        "state": "fires in Brazil",
        "questions": {
            "topic": {
                "type": "choice",
                "instructions": "Which topic?",
                "criteria": {"fire": "Fires", "loss": "Loss"},
            }
        },
    }


async def test_drops_an_answer_that_is_not_an_option():
    client, _ = _client(
        httpx.Response(200, json={"answers": {"topic": {"choice": "x"}}})
    )
    assert await decide("q", QUESTIONS, client=client) == {}


async def test_does_not_send_questions_with_fewer_than_two_options():
    client, requests = _client()
    one_option = {"q": Question("Which?", {"only": "Only"})}

    assert await decide("q", one_option, client=client) == {}
    assert requests == []


async def test_retries_once_on_overload(monkeypatch):
    monkeypatch.setattr(decisions.asyncio, "sleep", _no_sleep)
    ok = {"answers": {"topic": {"choice": "loss", "confidence": 0.6}}}
    client, requests = _client(
        httpx.Response(503, text="overloaded"), httpx.Response(200, json=ok)
    )

    answers = await decide("q", QUESTIONS, client=client)

    assert answers["topic"].choice == "loss"
    assert answers["topic"].probability == 0.6
    assert len(requests) == 2


async def test_raises_after_the_last_attempt(monkeypatch):
    monkeypatch.setattr(decisions.asyncio, "sleep", _no_sleep)
    client, _ = _client(
        httpx.Response(503, text="overloaded"),
        httpx.Response(503, text="overloaded"),
    )
    with pytest.raises(DecisionError, match="503"):
        await decide("q", QUESTIONS, client=client)


async def test_does_not_retry_a_bad_request():
    client, requests = _client(httpx.Response(400, text="blocked"))
    with pytest.raises(DecisionError, match="400"):
        await decide("q", QUESTIONS, client=client)
    assert len(requests) == 1


async def test_raises_without_a_key(monkeypatch):
    monkeypatch.setattr(SharedSettings, "openrouter_api_key", "")
    with pytest.raises(DecisionError, match="OPENROUTER_API_KEY"):
        await decide("q", QUESTIONS)


def test_gemini_is_the_default_provider():
    assert type(SharedSettings).model_fields["decision_provider"].default == (
        "gemini"
    )


async def test_gemini_sends_input_with_the_google_key(monkeypatch):
    monkeypatch.setattr(SharedSettings, "decision_provider", "gemini")
    client, requests = _client(_ok())

    answers = await decide("fires in Brazil", QUESTIONS, client=client)

    assert answers["topic"].choice == "fire"
    assert answers["topic"].probability == 0.8
    (request,) = requests
    assert str(request.url) == SharedSettings.gemini_decisions_url
    assert request.headers["x-goog-api-key"] == "google-key"
    assert "authorization" not in request.headers
    assert json.loads(request.content) == {
        "model": "gemini-decision-1",
        "input": "fires in Brazil",
        "questions": {
            "topic": {
                "type": "choice",
                "instructions": "Which topic?",
                "criteria": {"fire": "Fires", "loss": "Loss"},
            }
        },
    }


async def test_the_provider_argument_overrides_the_setting():
    client, requests = _client(_ok(), _ok())

    await decide("q", QUESTIONS, client=client, provider="gemini")
    await decide("q", QUESTIONS, client=client, provider="jev")

    assert [str(r.url) for r in requests] == [
        SharedSettings.gemini_decisions_url,
        SharedSettings.decisions_url,
    ]


async def test_gemini_raises_without_a_key(monkeypatch):
    monkeypatch.setattr(SharedSettings, "google_api_key", "")
    with pytest.raises(DecisionError, match="GOOGLE_API_KEY"):
        await decide("q", QUESTIONS, provider="gemini")


async def _no_sleep(_seconds):
    return None
