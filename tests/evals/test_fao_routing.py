"""Routing evals for the `fao-fra` skill.

These tests run the orchestrator (real LLM) on a small set of queries and
inspect the first tool call to verify the skill router behaves as the SPEC
expects:

- Positive cases — queries about country-reported / FAO / FRA statistics —
  must load the `fao-fra` skill via `read_skill`.
- Negative cases — sub-national, time-series, or non-FAO queries — must NOT
  load `fao-fra`.

Routing is the orchestrator's first decision. The first AIMessage either:
- Calls `read_skill(name=...)` and we assert which skill it loaded, or
- Calls a primitive directly (`pick_aoi`, `pick_dataset`, …) — counts as
  "not fao-fra" for the negative cases.

These hit live LLMs (`MODEL` / `SMALL_MODEL`). Run them on demand; treat
them as gating signal, not unit tests.

TODO — Judge-based golden Q&A evals:
  Build a `tests/evals/test_fao_golden.py` parametrised over ~20 country /
  variable pairs. For each pair, run the full skill (pick_aoi →
  pick_fra_variable → query_fra_data → generate_insights) and use an
  LLM judge (same shape as `tests/evals/judge.py`) to score: (i) correct
  variable selected, (ii) reporting years preserved (no interpolation),
  (iii) wording avoids "deforestation" for net change, (iv) FAO FRA 2025
  citation present in the insight. Include ~5 adversarial prompts
  (ambiguous variable, sub-national + FAO mention, custom date range +
  FAO mention) to verify the redirect paths.
"""

import uuid

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from src.agent.graph import fetch_zeno_anonymous

pytestmark = pytest.mark.asyncio(loop_scope="session")


# --- Cases -----------------------------------------------------------------

# Each positive case must route to the `fao-fra` skill on the first turn.
POSITIVE_CASES: list[str] = [
    "How much forest does Brazil have officially according to FAO?",
    "What does FAO FRA say about forest area in Indonesia?",
    "Show forest ownership categories in Sweden.",
    "Carbon stocks in DRC from FRA 2025.",
    "How has planted forest area changed in Vietnam between 1990 and 2025?",
    "What share of Brazil's forest is primary forest in the FAO report?",
]

# Each negative case must NOT route to the `fao-fra` skill. They are
# variously: sub-national, time-series, non-administrative geography, or
# clearly remote-sensing.
NEGATIVE_CASES: list[str] = [
    "Tree cover loss in Pará between 2020 and 2024.",
    "Show me deforestation alerts in the Amazon basin.",
    "Tree cover percentage in São Paulo state.",
    "Forest loss by driver in Indonesia in 2023.",
    "What can you do?",  # capabilities
]


# --- Helpers ---------------------------------------------------------------


async def _first_tool_calls(query: str) -> list[dict]:
    """Run one orchestrator turn and return the first AIMessage's tool calls.

    Returns an empty list if the orchestrator answered with plain text
    (no tool call) — that's a valid routing for some capability questions.
    """
    agent = await fetch_zeno_anonymous(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    input_state = {"messages": [HumanMessage(content=query)]}

    async for mode, payload in agent.astream(
        input_state,
        config=config,
        stream_mode=["updates"],
        subgraphs=False,
    ):
        if mode != "updates":
            continue
        for _node, update in payload.items():
            for msg in update.get("messages", []) or []:
                if isinstance(msg, AIMessage) and msg.tool_calls:
                    return msg.tool_calls
    return []


def _skill_name(tool_calls: list[dict]) -> str | None:
    """Return the skill name from the first `read_skill` call, if any."""
    for call in tool_calls:
        if call.get("name") == "read_skill":
            return (call.get("args") or {}).get("name")
    return None


# --- Positive cases — must route to fao-fra --------------------------------


@pytest.mark.parametrize("query", POSITIVE_CASES)
async def test_routes_to_fao_fra_skill(query: str):
    tool_calls = await _first_tool_calls(query)
    skill = _skill_name(tool_calls)
    assert skill == "fao-fra", (
        f"Expected `fao-fra` skill for query {query!r}; "
        f"first tool calls were {tool_calls!r}"
    )


# --- Negative cases — must NOT route to fao-fra ----------------------------


@pytest.mark.parametrize("query", NEGATIVE_CASES)
async def test_does_not_route_to_fao_fra(query: str):
    tool_calls = await _first_tool_calls(query)
    skill = _skill_name(tool_calls)
    assert skill != "fao-fra", (
        f"Did NOT expect `fao-fra` skill for query {query!r}; "
        f"first tool calls were {tool_calls!r}"
    )
