"""Unit tests for StopOnHumanFeedbackMiddleware — the hard backstop that
strips tools from the model call after a tool signals it's waiting on the
user, so the ReAct loop can't chain another tool call instead of stopping.
"""

import pytest
from langchain.agents.middleware.types import ModelRequest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agent.middleware import StopOnHumanFeedbackMiddleware

pytestmark = pytest.mark.asyncio


def _request(messages, tools=None) -> ModelRequest:
    return ModelRequest(
        model=object(),
        messages=messages,
        tools=tools if tools is not None else [object()],
    )


async def _capture_handler(request: ModelRequest) -> ModelRequest:
    """Test double: returns the request it was called with, so assertions
    can inspect what the middleware actually passed through."""
    return request


async def test_strips_tools_after_human_feedback_tool_message():
    request = _request(
        [
            HumanMessage("Show me deforestation somewhere ambiguous"),
            AIMessage("", tool_calls=[]),
            ToolMessage(
                "Which location did you mean?",
                tool_call_id="1",
                response_metadata={"msg_type": "human_feedback"},
            ),
        ]
    )

    result = await StopOnHumanFeedbackMiddleware().awrap_model_call(
        request, _capture_handler
    )

    assert result.tools == []


async def test_leaves_tools_untouched_after_ordinary_tool_message():
    request = _request(
        [
            HumanMessage("Pick a dataset"),
            AIMessage("", tool_calls=[]),
            ToolMessage("Selected dataset: TCL", tool_call_id="1"),
        ]
    )

    result = await StopOnHumanFeedbackMiddleware().awrap_model_call(
        request, _capture_handler
    )

    assert len(result.tools) == 1


async def test_detects_human_feedback_among_multiple_trailing_tool_messages():
    request = _request(
        [
            HumanMessage("Do two things"),
            AIMessage("", tool_calls=[]),
            ToolMessage("ok", tool_call_id="1"),
            ToolMessage(
                "Which one?",
                tool_call_id="2",
                response_metadata={"msg_type": "human_feedback"},
            ),
        ]
    )

    result = await StopOnHumanFeedbackMiddleware().awrap_model_call(
        request, _capture_handler
    )

    assert result.tools == []


async def test_ignores_human_feedback_tag_from_an_earlier_turn():
    """Only the most recent run of ToolMessages (since the last non-tool
    message) should count — an older human_feedback tag followed by a
    fresh AIMessage/ToolMessage pair means that ambiguity was resolved."""
    request = _request(
        [
            HumanMessage("ambiguous request"),
            AIMessage("", tool_calls=[]),
            ToolMessage(
                "Which one?",
                tool_call_id="1",
                response_metadata={"msg_type": "human_feedback"},
            ),
            HumanMessage("the second one"),
            AIMessage("", tool_calls=[]),
            ToolMessage("Selected dataset: TCL", tool_call_id="2"),
        ]
    )

    result = await StopOnHumanFeedbackMiddleware().awrap_model_call(
        request, _capture_handler
    )

    assert len(result.tools) == 1
