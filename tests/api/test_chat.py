"""POST /api/chat: input_source / nudge_response reach stream_chat parsed."""

from unittest.mock import patch

import pytest


@pytest.fixture
def captured_stream_kwargs():
    captured: dict = {}

    async def _mock_stream(*args, **kwargs):
        captured.update(kwargs)
        yield b'{"node": "agent", "update": "{}"}\n'

    async def _thread_name(query: str) -> str:
        return "Test thread"

    with (
        patch("src.api.routers.chat.stream_chat", _mock_stream),
        patch("src.api.routers.chat.generate_thread_name", _thread_name),
    ):
        yield captured


async def _post(client, thread_id: str, **body):
    return await client.post(
        "/api/chat",
        json={"query": "Tree cover loss", "thread_id": thread_id, **body},
        headers={"Authorization": "Bearer test-token"},
    )


@pytest.mark.asyncio
async def test_chat_defaults_input_source_to_typed(
    client, auth_override, captured_stream_kwargs
):
    auth_override("chat-input-typed")
    response = await _post(client, "chat-input-typed-thread")

    assert response.status_code == 200
    assert captured_stream_kwargs["input_source"] == "typed"
    assert captured_stream_kwargs["nudge_response"] is None


@pytest.mark.asyncio
async def test_chat_passes_nudge_click_through(
    client, auth_override, captured_stream_kwargs
):
    auth_override("chat-input-nudge")
    response = await _post(
        client,
        "chat-input-nudge-thread",
        input_source="nudge",
        nudge_response={"type": "dataset_choice", "option_index": 0},
    )

    assert response.status_code == 200
    assert captured_stream_kwargs["input_source"] == "nudge"
    assert captured_stream_kwargs["nudge_response"] == {
        "type": "dataset_choice",
        "option_index": 0,
    }


@pytest.mark.asyncio
async def test_chat_maps_legacy_human_input_to_nudge(
    client, auth_override, captured_stream_kwargs
):
    auth_override("chat-input-legacy")
    response = await _post(
        client, "chat-input-legacy-thread", query_type="human_input"
    )

    assert response.status_code == 200
    assert captured_stream_kwargs["input_source"] == "nudge"
    assert "query_type" not in captured_stream_kwargs


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"input_source": "voice"},
        {"input_source": "nudge", "nudge_response": {"type": "confirm"}},
        {"nudge_response": {"type": "confirm", "option_index": 0}},
    ],
)
async def test_chat_rejects_invalid_input_source_payloads(
    client, auth_override, captured_stream_kwargs, body
):
    auth_override("chat-input-invalid")
    response = await _post(client, "chat-input-invalid-thread", **body)

    assert response.status_code == 422
    assert captured_stream_kwargs == {}
