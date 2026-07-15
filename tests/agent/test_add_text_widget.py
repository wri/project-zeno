"""Tests for the add_text_widget agent tool."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from src.agent.tools.add_text_widget import add_text_widget
from src.shared.request_context import bound_user_id

NOTE = "# Deforestation summary\n\nTree cover loss rose 12% in 2024."


def _content(command):
    return command.update["messages"][0].content


def _dashboard(user_id="user-1", name="Paraná"):
    return SimpleNamespace(
        id=uuid4(), user_id=user_id, name=name, is_public=False
    )


def _patches(dashboard, widget_id="widget-1"):
    return (
        patch(
            "src.api.repositories.dashboard_writer.get_dashboard",
            new=AsyncMock(return_value=dashboard),
        ),
        patch(
            "src.api.repositories.dashboard_writer.add_widget",
            new=AsyncMock(return_value=widget_id),
        ),
    )


async def test_add_text_widget_happy_path():
    dashboard = _dashboard()
    get_dash, add_widget = _patches(dashboard, widget_id="widget-42")
    state = {"dashboard_id": str(dashboard.id)}
    with (
        get_dash,
        add_widget as add_widget_mock,
        bound_user_id("user-1"),
    ):
        command = await add_text_widget.coroutine(
            text=NOTE, state=state, tool_call_id="t1"
        )

    message = command.update["messages"][0]
    assert message.status == "success"
    assert message.response_metadata == {
        "msg_type": "dashboard_updated",
        "dashboard_id": str(dashboard.id),
    }
    assert command.update["dashboard_id"] == str(dashboard.id)
    # The widget id is surfaced so the agent can edit the note later.
    assert "widget-42" in message.content

    add_widget_mock.assert_awaited_once()
    kwargs = add_widget_mock.await_args.kwargs
    assert kwargs["widget_type"] == "text"
    assert kwargs["config"] == {"text": NOTE}
    assert kwargs["position"] is None


async def test_add_text_widget_strips_whitespace():
    dashboard = _dashboard()
    get_dash, add_widget = _patches(dashboard)
    state = {"dashboard_id": str(dashboard.id)}
    with (
        get_dash,
        add_widget as add_widget_mock,
        bound_user_id("user-1"),
    ):
        await add_text_widget.coroutine(
            text=f"  {NOTE}\n", state=state, tool_call_id="t1"
        )
    assert add_widget_mock.await_args.kwargs["config"] == {"text": NOTE}


async def test_add_text_widget_position_passthrough():
    dashboard = _dashboard()
    get_dash, add_widget = _patches(dashboard)
    state = {"dashboard_id": str(dashboard.id)}
    with (
        get_dash,
        add_widget as add_widget_mock,
        bound_user_id("user-1"),
    ):
        await add_text_widget.coroutine(
            text=NOTE, position=0, state=state, tool_call_id="t1"
        )
    assert add_widget_mock.await_args.kwargs["position"] == 0


async def test_add_text_widget_falls_back_to_view_context():
    dashboard = _dashboard()
    get_dash, add_widget = _patches(dashboard)
    state = {
        "view_context": {
            "page": "dashboard",
            "dashboard_id": str(dashboard.id),
        },
    }
    with (
        get_dash,
        add_widget,
        bound_user_id("user-1"),
    ):
        command = await add_text_widget.coroutine(
            text=NOTE, state=state, tool_call_id="t1"
        )
    assert command.update["messages"][0].status == "success"
    assert command.update["dashboard_id"] == str(dashboard.id)


async def test_add_text_widget_rejects_empty_text():
    with bound_user_id("user-1"):
        command = await add_text_widget.coroutine(
            text="   \n", state={}, tool_call_id="t1"
        )
    assert command.update["messages"][0].status == "error"
    assert "text is empty" in _content(command)


async def test_add_text_widget_requires_dashboard():
    with bound_user_id("user-1"):
        command = await add_text_widget.coroutine(
            text=NOTE, state={}, tool_call_id="t1"
        )
    assert command.update["messages"][0].status == "error"
    assert "No dashboard to add to" in _content(command)


async def test_add_text_widget_owner_only():
    # A public dashboard someone else owns is readable but not editable.
    dashboard = _dashboard(user_id="someone-else")
    dashboard.is_public = True
    get_dash, add_widget = _patches(dashboard)
    with (
        get_dash,
        add_widget as add_widget_mock,
        bound_user_id("user-1"),
    ):
        command = await add_text_widget.coroutine(
            text=NOTE,
            dashboard_id=str(dashboard.id),
            state={},
            tool_call_id="t1",
        )
    assert command.update["messages"][0].status == "error"
    assert "not found or not editable" in _content(command)
    add_widget_mock.assert_not_awaited()


async def test_add_text_widget_dashboard_vanishes_mid_write():
    dashboard = _dashboard()
    get_dash, add_widget = _patches(dashboard, widget_id=None)
    with (
        get_dash,
        add_widget,
        bound_user_id("user-1"),
    ):
        command = await add_text_widget.coroutine(
            text=NOTE,
            dashboard_id=str(dashboard.id),
            state={},
            tool_call_id="t1",
        )
    assert command.update["messages"][0].status == "error"
    assert "disappeared" in _content(command)
