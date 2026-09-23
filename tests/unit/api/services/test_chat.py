"""stream_chat: the LangChain config handed to the graph carries the
per-turn Langfuse trace name, tags and metadata."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.api.services import chat as chat_service

BASE = {"langfuse_user_id": "user-1", "langfuse_session_id": "thread-1"}
PENDING_NUDGE = {
    "type": "dataset_choice",
    "options": ["Tree cover loss", "Tree cover gain"],
}


class _FakeZeno:
    def __init__(self, state_values: dict):
        self._state_values = state_values
        self.config = None

    async def aget_state(self, config):
        return SimpleNamespace(values=self._state_values)

    async def astream(self, state_updates, config, **kwargs):
        self.config = config
        yield {"agent": {"messages": []}}


@pytest.fixture
def fake_zeno(monkeypatch):
    def _install(state_values: dict) -> _FakeZeno:
        zeno = _FakeZeno(state_values)

        async def _fetch_zeno(**kwargs):
            return zeno

        async def _resolve_language(**kwargs):
            return None

        monkeypatch.setattr(chat_service, "fetch_zeno", _fetch_zeno)
        monkeypatch.setattr(
            chat_service, "resolve_language", _resolve_language
        )
        handler = MagicMock(last_trace_id=None)
        monkeypatch.setattr(
            chat_service, "CallbackHandler", MagicMock(return_value=handler)
        )
        return zeno

    return _install


async def _run(**kwargs) -> None:
    async for _ in chat_service.stream_chat(
        thread_id="thread-1", langfuse_metadata=dict(BASE), **kwargs
    ):
        pass


async def test_typed_turn_config(fake_zeno):
    zeno = fake_zeno({"nudge": PENDING_NUDGE})
    await _run(query="Deforestation in Brazil", view_context={"page": "map"})

    assert zeno.config["run_name"] == "chat_turn"
    assert zeno.config["metadata"] == {
        **BASE,
        "langfuse_tags": ["input:typed"],
        "input_source": "typed",
        "nudge_match": False,
        "ui_action_only": False,
        "page": "map",
    }


async def test_nudge_click_with_matching_pending_nudge_config(fake_zeno):
    zeno = fake_zeno({"nudge": PENDING_NUDGE})
    await _run(
        query="Tree cover gain",
        input_source="nudge",
        nudge_response={"type": "dataset_choice", "option_index": 1},
        ff="experimental",
    )

    assert zeno.config["run_name"] == "chat_turn"
    assert zeno.config["metadata"] == {
        **BASE,
        "langfuse_tags": ["input:nudge", "nudge:dataset_choice"],
        "input_source": "nudge",
        "nudge_type": "dataset_choice",
        "nudge_option_index": 1,
        "nudge_match": True,
        "nudge_match_type": "dataset_choice",
        "nudge_match_index": 1,
        "ui_action_only": False,
        "ff": "experimental",
    }


async def test_new_thread_without_state_is_not_a_match(fake_zeno):
    zeno = fake_zeno({})
    await _run(query="Tree cover gain", input_source="nudge")

    assert zeno.config["metadata"]["nudge_match"] is False
    assert zeno.config["metadata"]["langfuse_tags"] == ["input:nudge"]


async def test_ui_action_only_turn_never_matches(fake_zeno):
    zeno = fake_zeno({"nudge": PENDING_NUDGE})
    await _run(query="Tree cover gain", ui_action_only=True)

    assert zeno.config["metadata"]["nudge_match"] is False
    assert zeno.config["metadata"]["ui_action_only"] is True
