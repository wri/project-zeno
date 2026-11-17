"""add_dashboard_item and edit_dashboard_item dispatch to the seven tools."""

import pytest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from src.agent.agent_config import default_registry
from src.agent.tools import dashboard_items as items


def _recorder(calls, name, reply="ok"):
    async def _coroutine(**kwargs):
        calls.append((name, kwargs))
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=reply, tool_call_id=kwargs["tool_call_id"]
                    )
                ]
            }
        )

    return _coroutine


@pytest.fixture
def calls(monkeypatch):
    recorded = []
    for name in (
        "add_to_dashboard",
        "add_map_widget",
        "add_text_widget",
        "add_dashboard_section",
        "edit_text_widget",
        "edit_dashboard_section",
        "move_dashboard_widget",
    ):
        tool = getattr(items, name)
        monkeypatch.setattr(
            tool, "coroutine", _recorder(recorded, name, f"use {name} again")
        )
    return recorded


async def _add(**kwargs):
    return await items.add_dashboard_item.coroutine(
        tool_call_id="t1", **kwargs
    )


async def _edit(**kwargs):
    return await items.edit_dashboard_item.coroutine(
        tool_call_id="t1", **kwargs
    )


def _content(command):
    return command.update["messages"][0].content


async def test_add_kinds_reach_their_tool(calls):
    await _add(kind="insight", insight_id="i1", section="Fires")
    await _add(kind="map", layer="imagery", title="Imagery")
    await _add(kind="text", text="A note", position=2)
    await _add(kind="section", title="Fires", description="Why")
    assert [name for name, _ in calls] == [
        "add_to_dashboard",
        "add_map_widget",
        "add_text_widget",
        "add_dashboard_section",
    ]
    assert calls[0][1]["insight_id"] == "i1"
    assert calls[0][1]["section"] == "Fires"
    assert calls[1][1]["layer"] == "imagery"
    assert calls[2][1]["position"] == 2
    assert calls[3][1]["description"] == "Why"


async def test_edit_kinds_reach_their_tool(calls):
    await _edit(kind="text", text="New", widget_id="w1")
    await _edit(kind="section", section="Fires", title="Burns")
    await _edit(kind="move", widget_id="w2", ungroup=True)
    assert [name for name, _ in calls] == [
        "edit_text_widget",
        "edit_dashboard_section",
        "move_dashboard_widget",
    ]
    assert calls[2][1]["ungroup"] is True


@pytest.mark.parametrize(
    "call, missing",
    [
        (lambda: _add(kind="map"), "layer"),
        (lambda: _add(kind="text"), "text"),
        (lambda: _add(kind="section"), "title"),
        (lambda: _edit(kind="text"), "text"),
        (lambda: _edit(kind="move"), "widget_id"),
    ],
)
async def test_missing_argument_is_an_error(calls, call, missing):
    command = await call()
    assert not calls
    assert f"`{missing}` is required" in _content(command)
    assert command.update["messages"][0].status == "error"


async def test_long_section_title_is_an_error(calls):
    command = await _add(kind="section", title="x" * 101)
    assert not calls
    assert "more than 100" in _content(command)


async def test_replies_name_the_new_tools(calls):
    command = await _add(kind="text", text="A note")
    assert _content(command) == 'use add_dashboard_item(kind="text") again'
    command = await _edit(kind="move", widget_id="w1")
    assert _content(command) == 'use edit_dashboard_item(kind="move") again'


def test_concise_profile_binds_the_two_tools_only():
    concise = default_registry.resolve("concise").tool_names()
    default = default_registry.resolve(None).tool_names()
    assert {"add_dashboard_item", "edit_dashboard_item"} <= concise
    assert not concise & set(items.REPLACED_TOOLS)
    assert set(items.REPLACED_TOOLS) <= default
    assert not {"add_dashboard_item", "edit_dashboard_item"} & default
