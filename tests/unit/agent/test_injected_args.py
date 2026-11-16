"""Injected tool arguments must not reach the model.

A tool argument annotated with ``InjectedState`` (or another injected type)
is filled by the ToolNode at run time. The model must not see it in the
tool schema: it costs tokens on each model call and the model can fill it.
``Annotated[Dict, InjectedState] | None`` hides the marker inside a union,
so the schema filter of langchain-core keeps the argument. The correct
form is ``Annotated[Optional[Dict], InjectedState] = None``.
"""

import types
import typing
from typing import Annotated, get_args, get_origin, get_type_hints

import pytest
from langchain_core.tools import InjectedToolArg, InjectedToolCallId
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.prebuilt import InjectedState, InjectedStore
from langgraph.prebuilt.tool_node import _get_all_injected_args

from src.agent.agent_config import default_registry

_INJECTED = (InjectedState, InjectedStore, InjectedToolArg, InjectedToolCallId)


def _is_injected(hint) -> bool:
    """True when ``hint`` carries an injected marker at any depth."""
    if get_origin(hint) is Annotated:
        base, *meta = get_args(hint)
        if any(
            isinstance(m, _INJECTED)
            or (isinstance(m, type) and issubclass(m, _INJECTED))
            for m in meta
        ):
            return True
        return _is_injected(base)
    return any(_is_injected(arg) for arg in get_args(hint))


def _injected_params(tool) -> set[str]:
    func = getattr(tool, "coroutine", None) or getattr(tool, "func", None)
    if func is None:
        return set()
    hints = get_type_hints(func, include_extras=True)
    return {name for name, hint in hints.items() if _is_injected(hint)}


def _bound_tools():
    seen = {}
    for cfg in default_registry.configs():
        for tool in cfg.bound_tools():
            seen[(cfg.name, tool.name)] = tool
    return seen


_TOOLS = _bound_tools()


@pytest.mark.parametrize("key", sorted(_TOOLS), ids=lambda k: f"{k[0]}-{k[1]}")
def test_schema_has_no_injected_argument(key):
    tool = _TOOLS[key]
    properties = convert_to_openai_tool(tool)["function"]["parameters"].get(
        "properties", {}
    )
    injected = _injected_params(tool)
    assert "state" not in properties
    assert not injected & properties.keys()


@pytest.mark.parametrize("key", sorted(_TOOLS), ids=lambda k: f"{k[0]}-{k[1]}")
def test_tool_node_still_injects_the_state(key):
    tool = _TOOLS[key]
    func = getattr(tool, "coroutine", None) or getattr(tool, "func", None)
    hints = get_type_hints(func, include_extras=True) if func else {}
    state_params = {
        name
        for name, hint in hints.items()
        if get_origin(hint) is Annotated
        and any(
            m is InjectedState or isinstance(m, InjectedState)
            for m in get_args(hint)[1:]
        )
    }
    assert state_params <= set(_get_all_injected_args(tool).state)


def test_some_tools_declare_injected_state():
    """Guard the guard: the helper finds the injected arguments."""
    with_state = {
        name
        for (_, name), tool in _TOOLS.items()
        if "state" in _injected_params(tool)
    }
    assert {"pick_aoi", "generate_insights", "add_to_dashboard"} <= with_state


def test_union_form_is_not_used():
    """The broken form must not come back: no injected marker in a union."""
    for tool in _TOOLS.values():
        func = getattr(tool, "coroutine", None) or getattr(tool, "func", None)
        if func is None:
            continue
        for name, hint in get_type_hints(func, include_extras=True).items():
            if get_origin(hint) in (typing.Union, types.UnionType):
                assert not _is_injected(hint), f"{tool.name}.{name}"
