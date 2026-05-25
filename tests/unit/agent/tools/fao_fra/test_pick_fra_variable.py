"""Unit tests for the FAO-FRA variable-selection subagent.

No LLM calls — the structured-output chain is monkeypatched to return canned
`VariableSelection` instances. We assert (a) the chosen variable surfaces in
the ToolMessage, (b) hallucinated variable names produce a recoverable
ToolMessage rather than crashing, and (c) the rendered prompt covers every
key in `VARIABLE_MAP`.
"""

from unittest.mock import MagicMock

import pytest

from src.agent.subagents.pick_fra_variable import (
    VARIABLE_MAP,
    VariableSelection,
    VariableSelector,
    pick_fra_variable,
)
from src.agent.subagents.pick_fra_variable.variable_map import (
    VALID_VARIABLES,
    render_variable_table,
)

# ---------------------------------------------------------------------------
# Variable map structural shape
# ---------------------------------------------------------------------------


def test_variable_map_has_required_fields_for_every_entry():
    required = {"table", "variables", "unit", "description"}
    for name, entry in VARIABLE_MAP.items():
        missing = required - entry.keys()
        assert not missing, f"{name} missing fields: {missing}"
        assert isinstance(entry["table"], str) and entry["table"]
        assert isinstance(entry["variables"], list)
        assert isinstance(entry["unit"], str) and entry["unit"]
        assert isinstance(entry["description"], str) and entry["description"]


def test_valid_variables_matches_map_keys():
    assert VALID_VARIABLES == sorted(VARIABLE_MAP.keys())


def test_render_variable_table_includes_every_variable():
    rendered = render_variable_table()
    for name in VARIABLE_MAP:
        assert name in rendered
    for entry in VARIABLE_MAP.values():
        assert entry["description"] in rendered


# ---------------------------------------------------------------------------
# VariableSelector — happy path and hallucination handling
# ---------------------------------------------------------------------------


class _StubChain:
    """Tiny async-invocable that returns a canned VariableSelection."""

    def __init__(self, selection: VariableSelection) -> None:
        self._selection = selection
        self.calls: list[dict] = []

    async def ainvoke(self, payload: dict) -> VariableSelection:
        self.calls.append(payload)
        return self._selection


def _install_stub_chain(
    monkeypatch, selection: VariableSelection
) -> _StubChain:
    """Monkeypatch SMALL_MODEL.with_structured_output to yield our stub chain."""
    from src.agent.subagents.pick_fra_variable import tool as subagent_mod

    stub = _StubChain(selection)
    chain_mock = MagicMock()
    chain_mock.__or__ = MagicMock(return_value=stub)

    structured_model = MagicMock()
    structured_model.ainvoke = stub.ainvoke

    fake_small_model = MagicMock()
    fake_small_model.with_structured_output = MagicMock(
        return_value=structured_model
    )
    monkeypatch.setattr(subagent_mod, "SMALL_MODEL", fake_small_model)
    # The selector also uses the `|` operator on the prompt template. We
    # patch the chain construction directly by returning `stub` from
    # `__or__` on the template; simpler is to patch `_select` to call the
    # stub directly.
    return stub


@pytest.fixture
def stub_chain(monkeypatch):
    """Helper that patches the selector's `_select` to return a canned value."""

    def _patch(variable: str, reason: str = "test reason") -> None:
        from src.agent.subagents.pick_fra_variable import tool as subagent_mod

        async def fake_select(self, question):
            return VariableSelection(variable=variable, reason=reason)

        monkeypatch.setattr(
            subagent_mod.VariableSelector, "_select", fake_select
        )

    return _patch


async def test_resolve_returns_tool_message_with_variable_name(stub_chain):
    stub_chain("carbon_stock", reason="user asked about carbon")
    cmd = await VariableSelector().resolve(
        "How much carbon does Brazil's forest store?",
        tool_call_id="tc-1",
    )
    messages = cmd.update["messages"]
    assert len(messages) == 1
    content = messages[0].content
    assert "carbon_stock" in content
    assert "megatonnes CO2e" in content  # unit surfaced from VARIABLE_MAP
    assert "Reason: user asked about carbon" in content
    assert messages[0].tool_call_id == "tc-1"


async def test_resolve_handles_hallucinated_variable_name(stub_chain):
    stub_chain("not_a_real_variable")
    cmd = await VariableSelector().resolve(
        "Some question", tool_call_id="tc-2"
    )
    messages = cmd.update["messages"]
    assert len(messages) == 1
    content = messages[0].content
    assert "not a recognised FAO FRA variable" in content
    # All valid variables should be listed in the error so the orchestrator
    # can retry with a hint.
    assert "carbon_stock" in content
    assert "forest_area" in content


async def test_resolve_does_not_write_to_state(stub_chain):
    """The chosen variable lives in the ToolMessage only — not in state.
    Re-callability depends on this; if the variable were persisted, a
    second call would fight with the first."""
    stub_chain("forest_area")
    cmd = await VariableSelector().resolve("Forest area?", tool_call_id="t")
    assert set(cmd.update.keys()) == {"messages"}


async def test_tool_wrapper_invokes_resolver(stub_chain):
    stub_chain("ownership", reason="ownership query")
    cmd = await pick_fra_variable.ainvoke(
        {
            "type": "tool_call",
            "name": "pick_fra_variable",
            "id": "tc-3",
            "args": {
                "question": "Who owns Sweden's forests?",
                "tool_call_id": "tc-3",
            },
        }
    )
    assert "ownership" in cmd.update["messages"][0].content
