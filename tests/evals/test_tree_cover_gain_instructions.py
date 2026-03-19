"""
Eval cases for Tree Cover Gain (dataset 5) tiered instructions.

Fixture data: Indonesia cumulative gain across 4 periods.
"""

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


# ---------------------------------------------------------------------------
# Behavior 1: Bar chart with one bar per period
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    "Show tree cover gain in Indonesia",
    "How much tree cover was gained in Indonesia?",
    "Indonesia tree cover gain by period",
    "Display tree cover gain for Indonesia across all periods",
    "bar chart of tree cover gain in Indonesia",
    "Tree cover gain in Indonesia 2000-2020",
    "How much new tree cover appeared in Indonesia?",
    "Indonesia forest regrowth data",
    "show gain area per period for Indonesia",
    "cumulative tree cover gain in Indonesia",
    "Indonesia: tree cover gain across time periods",
    "chart tree cover gain for Indonesia",
    "how much tree cover did Indonesia gain?",
    "tree cover gain breakdown for Indonesia",
    "Indonesia tree gain area by time period",
])
async def test_bar_chart_per_period(query, tree_cover_gain_state, run_insights, judge):
    """Must show bar chart with one bar per time period."""
    result = await run_insights(query, tree_cover_gain_state)

    verdict = await judge(
        query=query,
        rubric="""
        1. The chart type must be "bar".
        2. The x-axis should represent the time periods (e.g., 2000-2020, 2005-2020,
           2010-2020, 2015-2020).
        3. The y-axis should represent area in hectares.
        """,
        tool_output=result,
    )

    assert verdict.passed, f"FAIL [{query[:50]}]: {verdict.comment}"


# ---------------------------------------------------------------------------
# Behavior 2: Does NOT use "restoration" terminology
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    "How much forest was restored in Indonesia?",
    "Show forest restoration in Indonesia",
    "Indonesia reforestation and restoration data",
    "How successful is forest restoration in Indonesia?",
    "restored forest area in Indonesia",
    "Show me the restoration of forests in Indonesia",
    "Indonesia restoration statistics",
    "what area has been reforested in Indonesia?",
    "forest recovery in Indonesia",
    "how much land was reforested in Indonesia?",
    "Indonesia: forest area restored since 2000",
    "restoration vs deforestation in Indonesia",
    "tree planting and restoration results for Indonesia",
    "Indonesia afforestation and restoration progress",
    "show reforestation achievements in Indonesia",
])
async def test_does_not_use_restoration(query, tree_cover_gain_state, run_insights, judge):
    """Must use 'tree cover gain' not 'restoration'."""
    result = await run_insights(query, tree_cover_gain_state)

    verdict = await judge(
        query=query,
        rubric="""
        1. The insight text must use "tree cover gain" (or similar like "gain in tree cover")
           as the primary term, NOT "restoration", "reforestation", or "afforestation".
        2. If "restoration" is mentioned, it must include a clear caveat that tree cover gain
           does NOT equate to restoration — it may include plantation cycles, natural regrowth,
           or land abandonment.
        3. The term "tree cover gain" should appear at least once in the insight text.
        """,
        tool_output=result,
    )

    assert verdict.passed, f"FAIL [{query[:50]}]: {verdict.comment}"


# ---------------------------------------------------------------------------
# Behavior 3: Refuses net gain/loss calculation
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    "What is the net forest change in Indonesia?",
    "Calculate net tree cover change for Indonesia",
    "Net gain minus loss for Indonesia forests",
    "How much forest did Indonesia gain vs lose?",
    "net deforestation in Indonesia",
    "subtract loss from gain for Indonesia",
    "Indonesia: net change in tree cover",
    "is Indonesia gaining or losing forest overall?",
    "net forest area change in Indonesia",
    "compare gain and loss to get net change for Indonesia",
    "Indonesia net tree cover balance",
    "total net reforestation in Indonesia",
    "combine gain and loss data for Indonesia",
    "Indonesia net forest change calculation",
    "what's the balance of gain vs loss in Indonesia?",
])
async def test_refuses_net_calculation(query, tree_cover_gain_state, run_insights, judge):
    """Must refuse net gain/loss — methodologies differ between datasets."""
    result = await run_insights(query, tree_cover_gain_state)

    if result["refused"]:
        return

    verdict = await judge(
        query=query,
        rubric="""
        1. The output must indicate that net change CANNOT be calculated by combining
           gain and loss datasets because the methodologies differ.
        2. This warning must appear in the insight text, tool message, or chart context.
        3. The output should NOT present a net change value calculated by subtracting
           loss from gain.
        """,
        tool_output=result,
    )

    assert verdict.passed, f"FAIL [{query[:50]}]: {verdict.comment}"
