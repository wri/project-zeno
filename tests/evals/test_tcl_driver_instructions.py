"""
Eval cases for Tree Cover Loss by Dominant Driver (dataset 8) tiered instructions.

Each behavior is tested with ~15 prompt phrasings for robustness.
Tests call real Gemini Flash + Haiku judge — no LLM mocks.

Note: Fixture data is for Indonesia, so all queries target that region.
Different phrasings test instruction-following, not dataset selection.
"""

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


# ---------------------------------------------------------------------------
# Behavior 1: Pie chart or table only, NO timeseries
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    # Original 4
    "What are the main drivers of tree cover loss in Indonesia?",
    "Show me the causes of forest loss in Indonesia",
    "Break down tree cover loss by driver for Indonesia",
    "Why is Indonesia losing forest? Show the driver breakdown",
    # Formal
    "Provide a breakdown of tree cover loss by dominant driver for Indonesia over 2001-2024",
    "Categorize the causes of tree cover loss in Indonesia by driver class",
    # Casual
    "drivers of forest loss in Indonesia",
    "what caused the most tree loss in Indonesia?",
    "Indonesia TCL drivers breakdown",
    # Variant terminology
    "What's driving deforestation in Indonesia?",
    "Main deforestation drivers for Indonesia — show as a chart",
    "Forest clearing causes in Indonesia — pie chart please",
    # Edge cases
    "Which driver accounts for the most tree cover loss in Indonesia?",
    "Rank the drivers of canopy loss in Indonesia",
    "Give me the proportions of each forest loss cause in Indonesia",
])
async def test_pie_or_table_not_timeseries(query, tcl_driver_state, run_insights, judge):
    """Must produce pie chart or table. NOT line, bar, area, or any timeseries."""
    result = await run_insights(query, tcl_driver_state)

    verdict = await judge(
        query=query,
        rubric="""
        1. The chart type MUST be "pie" or "table".
        2. The chart type must NOT be "line", "bar", "stacked-bar", "grouped-bar",
           "area", or "scatter".
        3. The chart data should show driver categories with their corresponding
           area or emissions values, NOT a time-based breakdown.
        """,
        tool_output=result,
    )

    assert verdict.passed, f"FAIL [{query[:50]}]: {verdict.comment}"


# ---------------------------------------------------------------------------
# Behavior 2: Excludes Unknown driver class
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    # Original 3
    "Show the driver breakdown for tree cover loss in Indonesia",
    "What caused forest loss in Indonesia? Pie chart please",
    "Tree cover loss drivers in Indonesia over 2001-2024",
    # Formal
    "Provide a comprehensive breakdown of all tree cover loss driver classes for Indonesia",
    "List each driver category and its contribution to tree cover loss in Indonesia",
    # Casual
    "all the drivers of loss in Indonesia",
    "indonesia tcl by cause, show everything",
    # Variant phrasing
    "Show ALL driver classes for Indonesia tree cover loss",
    "Every category of forest loss driver in Indonesia",
    "Full breakdown including all categories for Indonesia",
    "Don't leave anything out — show all drivers for Indonesia TCL",
    "What percentage does each driver contribute in Indonesia?",
    # Edge cases
    "Complete driver distribution for Indonesia tree cover loss",
    "Exhaustive list of tree cover loss drivers in Indonesia",
    "Every single driver category for Indonesia forest loss",
])
async def test_excludes_unknown_driver(query, tcl_driver_state, run_insights, judge):
    """Chart data must not include 'Unknown' as a driver category."""
    result = await run_insights(query, tcl_driver_state)

    verdict = await judge(
        query=query,
        rubric="""
        1. The chart data must NOT contain any row or segment where the driver/category
           is "Unknown" (case-insensitive).
        2. Check the chart data preview for any occurrence of "Unknown" in category/driver columns.
        3. All 7 named driver classes may appear (Permanent agriculture, Shifting cultivation,
           Logging, Wildfire, Hard commodities, Settlements and infrastructure,
           Other natural disturbances) but "Unknown" must be excluded.
        """,
        tool_output=result,
    )

    assert verdict.passed, f"FAIL [{query[:50]}]: {verdict.comment}"


# ---------------------------------------------------------------------------
# Behavior 3: Refuses annual timeseries, suggests base TCL
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    # Original 3
    "Show me annual tree cover loss by driver in Indonesia from 2010 to 2024",
    "What's the trend in deforestation drivers over time in Indonesia?",
    "Year by year breakdown of forest loss causes in Indonesia",
    # Formal
    "Provide a time series of tree cover loss by driver class for Indonesia, 2001-2024",
    "How have the proportions of each driver changed annually in Indonesia?",
    # Casual
    "drivers over time for Indonesia",
    "trend of each driver year by year indonesia",
    # Variant phrasing
    "How did permanent agriculture as a driver change from 2010 to 2024 in Indonesia?",
    "Compare wildfire vs logging driver trends over time in Indonesia",
    "Show me 2015 vs 2020 driver composition for Indonesia",
    # Incorrect terminology
    "Annual deforestation by cause for Indonesia 2010-2024",
    "Yearly deforestation driver trends for Indonesia",
    # Edge cases
    "Is shifting cultivation increasing over time in Indonesia?",
    "Plot each driver's area over the years for Indonesia",
    "Timeline of tree cover loss by driver in Indonesia 2005-2024",
])
async def test_refuses_timeseries_suggests_tcl(query, tcl_driver_state, run_insights, judge):
    """Must refuse timeseries and suggest base Tree Cover Loss dataset."""
    result = await run_insights(query, tcl_driver_state)

    # If the tool itself refused (no chart data), that's a pass —
    # the code executor correctly declined to produce a timeseries
    if result["refused"]:
        return

    verdict = await judge(
        query=query,
        rubric="""
        1. The output must indicate that this dataset cannot produce annual timeseries
           or year-by-year trends. This can appear in the insight text or tool message.
        2. The chart data must NOT be organized by year/time (no year column as primary
           axis with multiple data points per year).
        3. The output should mention or suggest the base "Tree cover loss" dataset as an
           alternative for annual trends. The exact phrasing may vary but the intent
           must be clear.
        """,
        tool_output=result,
    )

    assert verdict.passed, f"FAIL [{query[:50]}]: {verdict.comment}"


# ---------------------------------------------------------------------------
# Behavior 4: Uses "tree cover loss" not "deforestation"
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    # Original 3
    "What are the deforestation drivers in Indonesia?",
    "Show causes of forest destruction in Indonesia",
    "Why is Indonesia being deforested? Show by driver",
    # Formal
    "Analyze the principal deforestation drivers affecting Indonesia",
    "Provide a categorical analysis of deforestation causes in Indonesia",
    # Casual
    "deforestation causes indonesia",
    "why is indonesia getting deforested?",
    # Variant terminology
    "Chart the deforestation crisis drivers in Indonesia",
    "Which deforestation driver is worst in Indonesia?",
    "forest destruction causes in Indonesia",
    "what's killing the forests in Indonesia?",
    "Indonesia: reasons for losing forest cover",
    # Edge cases — provocative terms
    "Clearcut drivers in Indonesia",
    "What's behind the Indonesian forest wipeout?",
    "Main causes of Indonesian jungle disappearing",
])
async def test_uses_tree_cover_loss_terminology(query, tcl_driver_state, run_insights, judge):
    """Insight text must use 'tree cover loss', not 'deforestation'."""
    result = await run_insights(query, tcl_driver_state)

    verdict = await judge(
        query=query,
        rubric="""
        1. The insight text must use the term "tree cover loss" (or close variants like
           "loss of tree cover") when describing the data.
        2. The insight text should NOT use the term "deforestation" to describe the results,
           UNLESS it is explicitly noting that "tree cover loss" is different from "deforestation"
           or warning the user about terminology.
        3. A brief mention like "often referred to as deforestation" as a clarification is acceptable,
           but the primary term used must be "tree cover loss".
        """,
        tool_output=result,
    )

    assert verdict.passed, f"FAIL [{query[:50]}]: {verdict.comment}"
