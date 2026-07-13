"""Tests for the edit_text_widget agent tool."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from src.agent.tools.edit_text_widget import edit_text_widget
from src.shared.request_context import bound_user_id

NEW_TEXT = "# Updated note\n\nRevised after the 2024 data pull."


def _content(command):
    return command.update["messages"][0].content


def _dashboard(user_id="user-1", name="Paraná", widgets=()):
    return SimpleNamespace(
        id=uuid4(),
        user_id=user_id,
        name=name,
        is_public=False,
        widgets=list(widgets),
    )


def _widget(widget_type="text", text="Old note.", dashboard_id=None):
    return SimpleNamespace(
        id=uuid4(),
        widget_type=widget_type,
        config={"text": text} if widget_type == "text" else {},
        dashboard_id=dashboard_id or uuid4(),
    )


def _patch_get_dashboard(dashboard):
    return patch(
        "src.api.repositories.dashboard_writer.get_dashboard",
        new=AsyncMock(return_value=dashboard),
    )


def _patch_get_widget(widget):
    return patch(
        "src.api.repositories.dashboard_writer.get_widget",
        new=AsyncMock(return_value=widget),
    )


def _patch_update_widget(result=True):
    return patch(
        "src.api.repositories.dashboard_writer.update_widget",
        new=AsyncMock(return_value=result),
    )


async def test_edit_text_widget_single_widget_on_dashboard():
    dashboard = _dashboard()
    widget = _widget(dashboard_id=dashboard.id)
    dashboard.widgets = [_widget("insight"), widget, _widget("map")]
    state = {"dashboard_id": str(dashboard.id)}
    with (
        _patch_get_dashboard(dashboard),
        _patch_update_widget() as update_mock,
        bound_user_id("user-1"),
    ):
        command = await edit_text_widget.coroutine(
            text=NEW_TEXT, state=state, tool_call_id="t1"
        )

    message = command.update["messages"][0]
    assert message.status == "success"
    assert message.response_metadata == {
        "msg_type": "dashboard_updated",
        "dashboard_id": str(dashboard.id),
    }
    assert command.update["dashboard_id"] == str(dashboard.id)
    assert str(widget.id) in message.content

    update_mock.assert_awaited_once()
    args, kwargs = update_mock.await_args
    assert args == (widget.id,)
    assert kwargs["config"] == {"text": NEW_TEXT}


async def test_edit_text_widget_explicit_widget_id():
    dashboard = _dashboard()
    widget = _widget(dashboard_id=dashboard.id)
    with (
        _patch_get_widget(widget),
        _patch_get_dashboard(dashboard),
        _patch_update_widget() as update_mock,
        bound_user_id("user-1"),
    ):
        command = await edit_text_widget.coroutine(
            text=NEW_TEXT,
            widget_id=str(widget.id),
            state={},
            tool_call_id="t1",
        )
    assert command.update["messages"][0].status == "success"
    update_mock.assert_awaited_once()


async def test_edit_text_widget_rejects_empty_text():
    with bound_user_id("user-1"):
        command = await edit_text_widget.coroutine(
            text="  \n ", state={}, tool_call_id="t1"
        )
    assert command.update["messages"][0].status == "error"
    assert "text is empty" in _content(command)


async def test_edit_text_widget_requires_dashboard_or_widget():
    with bound_user_id("user-1"):
        command = await edit_text_widget.coroutine(
            text=NEW_TEXT, state={}, tool_call_id="t1"
        )
    assert command.update["messages"][0].status == "error"
    assert "No dashboard to edit" in _content(command)


async def test_edit_text_widget_ambiguous_lists_candidates():
    dashboard = _dashboard()
    first = _widget(text="First note.", dashboard_id=dashboard.id)
    second = _widget(text="Second note.", dashboard_id=dashboard.id)
    dashboard.widgets = [first, second]
    with (
        _patch_get_dashboard(dashboard),
        _patch_update_widget() as update_mock,
        bound_user_id("user-1"),
    ):
        command = await edit_text_widget.coroutine(
            text=NEW_TEXT,
            dashboard_id=str(dashboard.id),
            state={},
            tool_call_id="t1",
        )
    assert command.update["messages"][0].status == "error"
    content = _content(command)
    assert "pass widget_id" in content
    assert str(first.id) in content
    assert str(second.id) in content
    update_mock.assert_not_awaited()


async def test_edit_text_widget_no_text_widget_on_dashboard():
    dashboard = _dashboard(widgets=[_widget("insight"), _widget("map")])
    with (
        _patch_get_dashboard(dashboard),
        _patch_update_widget() as update_mock,
        bound_user_id("user-1"),
    ):
        command = await edit_text_widget.coroutine(
            text=NEW_TEXT,
            dashboard_id=str(dashboard.id),
            state={},
            tool_call_id="t1",
        )
    assert command.update["messages"][0].status == "error"
    assert "No text widget" in _content(command)
    update_mock.assert_not_awaited()


async def test_edit_text_widget_unknown_widget_id():
    with (
        _patch_get_widget(None),
        _patch_update_widget() as update_mock,
        bound_user_id("user-1"),
    ):
        command = await edit_text_widget.coroutine(
            text=NEW_TEXT,
            widget_id=str(uuid4()),
            state={},
            tool_call_id="t1",
        )
    assert command.update["messages"][0].status == "error"
    assert "not found" in _content(command)
    update_mock.assert_not_awaited()


async def test_edit_text_widget_rejects_non_text_widget():
    widget = _widget("map")
    with (
        _patch_get_widget(widget),
        _patch_update_widget() as update_mock,
        bound_user_id("user-1"),
    ):
        command = await edit_text_widget.coroutine(
            text=NEW_TEXT,
            widget_id=str(widget.id),
            state={},
            tool_call_id="t1",
        )
    assert command.update["messages"][0].status == "error"
    assert "not a text widget" in _content(command)
    update_mock.assert_not_awaited()


async def test_edit_text_widget_owner_only():
    # The widget exists but lives on someone else's (public) dashboard:
    # same reply as a missing widget, and no write happens.
    dashboard = _dashboard(user_id="someone-else")
    dashboard.is_public = True
    widget = _widget(dashboard_id=dashboard.id)
    with (
        _patch_get_widget(widget),
        _patch_get_dashboard(dashboard),
        _patch_update_widget() as update_mock,
        bound_user_id("user-1"),
    ):
        command = await edit_text_widget.coroutine(
            text=NEW_TEXT,
            widget_id=str(widget.id),
            state={},
            tool_call_id="t1",
        )
    assert command.update["messages"][0].status == "error"
    assert "not editable" in _content(command)
    update_mock.assert_not_awaited()


async def test_edit_text_widget_vanishes_mid_write():
    dashboard = _dashboard()
    widget = _widget(dashboard_id=dashboard.id)
    dashboard.widgets = [widget]
    with (
        _patch_get_dashboard(dashboard),
        _patch_update_widget(result=False),
        bound_user_id("user-1"),
    ):
        command = await edit_text_widget.coroutine(
            text=NEW_TEXT,
            dashboard_id=str(dashboard.id),
            state={},
            tool_call_id="t1",
        )
    assert command.update["messages"][0].status == "error"
    assert "disappeared" in _content(command)
