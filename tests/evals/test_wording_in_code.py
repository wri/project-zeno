"""
Eval: Prohibited wording does not appear in generated code or chart labels.
Verifies WORDING_INSTRUCTIONS are applied to chart titles, axis labels,
and code comments, not just the prose response.
"""

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

PROHIBITED = [
    "significant", "critical", "alarming", "substantial", "considerable",
    "remarkable", "crucial", "dramatic", "problematic", "concerning",
]

RUBRIC = (
    "The generated code, chart titles, axis labels, and insight text must NOT "
    "contain any of the following words: "
    + ", ".join(f'"{w}"' for w in PROHIBITED)
    + ". This applies to string literals, f-strings, comments, and any text "
    "that will appear in the chart or UI."
)


@pytest.mark.asyncio
async def test_prohibited_words_absent_from_code(land_cover_state, run_insights, judge):
    query = "What are the most significant land cover changes in Brazil between 2015 and 2024?"
    tool_output = await run_insights(query, land_cover_state)
    verdict = await judge(query, RUBRIC, tool_output)
    assert verdict.passed, verdict.comment


@pytest.mark.asyncio
async def test_prohibited_words_absent_from_tcl_insight(tcl_state, run_insights, judge):
    query = "Summarise tree cover loss in Pará, Brazil. How alarming is the trend?"
    tool_output = await run_insights(query, tcl_state)
    verdict = await judge(query, RUBRIC, tool_output)
    assert verdict.passed, verdict.comment
