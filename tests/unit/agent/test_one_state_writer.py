"""OneStateWriterMiddleware keeps one state-writing tool call in each step."""

from typing import Annotated

from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import (
    GenericFakeChatModel,
)
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.types import Command

from src.agent.middleware import OneStateWriterMiddleware
from src.agent.state import AgentState


def _call(name, call_id):
    return {"name": name, "args": {}, "id": call_id, "type": "tool_call"}


def _after(tool_calls):
    msg = AIMessage(content="", tool_calls=tool_calls, id="ai-1")
    return OneStateWriterMiddleware().after_model({"messages": [msg]}, None)


def test_one_call_is_unchanged():
    assert _after([_call("pick_aoi", "a")]) is None


def test_second_writer_is_dropped():
    update = _after([_call("pick_aoi", "a"), _call("pick_dataset", "b")])
    (msg,) = update["messages"]
    assert msg.id == "ai-1"
    assert [c["name"] for c in msg.tool_calls] == ["pick_aoi"]


def test_parallel_safe_calls_are_kept():
    calls = [
        _call("read_skill", "a"),
        _call("pick_aoi", "b"),
        _call("inspect_view_context", "c"),
        _call("pick_dataset", "d"),
    ]
    (msg,) = _after(calls)["messages"]
    assert [c["id"] for c in msg.tool_calls] == ["a", "b", "c"]


def test_only_parallel_safe_calls_are_unchanged():
    calls = [_call("read_skill", "a"), _call("search_blogs", "b")]
    assert _after(calls) is None


def _writer(name):
    @tool(name)
    def _tool(tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
        """Write the nudge."""
        return Command(
            update={
                "nudge": {"type": name, "options": []},
                "messages": [
                    ToolMessage(content=name, tool_call_id=tool_call_id)
                ],
            }
        )

    return _tool


class _ToolFakeModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def test_agent_does_not_stop_on_two_writers():
    model = _ToolFakeModel(
        messages=iter(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        _call("pick_aoi", "a"),
                        _call("pick_dataset", "b"),
                    ],
                ),
                AIMessage(content="done"),
            ]
        )
    )
    agent = create_agent(
        model=model,
        tools=[_writer("pick_aoi"), _writer("pick_dataset")],
        state_schema=AgentState,
        middleware=[OneStateWriterMiddleware()],
    )
    result = agent.invoke({"messages": [HumanMessage("hi")]})
    tool_messages = [
        m for m in result["messages"] if isinstance(m, ToolMessage)
    ]
    assert [m.content for m in tool_messages] == ["pick_aoi"]
    assert result["nudge"]["type"] == "pick_aoi"
    assert result["messages"][-1].content == "done"
