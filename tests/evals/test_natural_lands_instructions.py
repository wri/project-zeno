"""
Eval cases for SBTN Natural Lands Map (dataset 3) tiered instructions.

Fixture data: Colombia natural/non-natural lands 2020.
"""

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


# ---------------------------------------------------------------------------
# Behavior 1: Bar or pie chart for natural vs non-natural
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    "What proportion of Colombia is natural vs non-natural land?",
    "Show the breakdown of natural and non-natural lands in Colombia",
    "How much of Colombia is natural land in 2020?",
    "Colombia natural lands map data — show proportions",
    "pie chart of natural vs non-natural areas in Colombia",
    "Natural vs non-natural land cover in Colombia",
    "What area of Colombia is natural ecosystem?",
    "Colombia: natural land extent 2020",
    "how much natural land does Colombia have?",
    "Show me natural vs managed land in Colombia",
    "proportion of natural ecosystems in Colombia",
    "Colombia natural lands breakdown",
    "what share of Colombia is natural in 2020?",
    "natural and non-natural areas in Colombia — bar chart",
    "Colombia SBTN natural lands baseline",
])
async def test_bar_or_pie_for_proportions(query, natural_lands_state, run_insights, judge):
    """Must use bar or pie chart for natural vs non-natural proportions."""
    result = await run_insights(query, natural_lands_state)

    verdict = await judge(
        query=query,
        rubric="""
        1. The chart type must be "bar" or "pie".
        2. The data should distinguish natural from non-natural land classes.
        3. Values should represent area in hectares.
        """,
        tool_output=result,
    )

    assert verdict.passed, f"FAIL [{query[:50]}]: {verdict.comment}"


# ---------------------------------------------------------------------------
# Behavior 2: Refuses change over time
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    "How has natural land in Colombia changed over time?",
    "Show the trend in natural land area in Colombia",
    "Has Colombia lost natural land since 2020?",
    "Natural land change in Colombia 2020-2024",
    "annual natural land area in Colombia",
    "Is Colombia losing natural ecosystems? Show the trend",
    "timeseries of natural lands in Colombia",
    "compare 2020 vs 2024 natural land in Colombia",
    "how much natural land did Colombia lose each year?",
    "Colombia natural land loss trend",
    "year by year natural ecosystem change in Colombia",
    "monthly natural land changes in Colombia",
    "natural land conversion rate in Colombia",
    "how fast is Colombia losing natural lands?",
    "Colombia: natural land trajectory 2020-2024",
])
async def test_refuses_change_over_time(query, natural_lands_state, run_insights, judge):
    """Must refuse change/trend questions — this is a 2020 snapshot only."""
    result = await run_insights(query, natural_lands_state)

    if result["refused"]:
        return

    verdict = await judge(
        query=query,
        rubric="""
        1. The output must indicate that this dataset is a single-year (2020) snapshot
           and CANNOT show change over time.
        2. The output should suggest using the Global Land Cover dataset for change analysis.
        3. The chart data must NOT show multiple years or a temporal progression.
        """,
        tool_output=result,
    )

    assert verdict.passed, f"FAIL [{query[:50]}]: {verdict.comment}"


# ---------------------------------------------------------------------------
# Behavior 3: Combines natural forest classes
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    "How much natural forest is in Colombia?",
    "Show the area of natural forest in Colombia",
    "Colombia natural forest extent 2020",
    "What area of Colombia is covered by natural forest?",
    "natural forest area in Colombia",
    "How much of Colombia's forest is natural?",
    "Colombia: total natural forest area",
    "natural forest coverage in Colombia 2020",
    "show me the natural forest in Colombia",
    "area of natural forests in Colombia",
    "how big are Colombia's natural forests?",
    "Colombia natural forest — total hectares",
    "natural forest baseline for Colombia",
    "what is the extent of natural forests in Colombia?",
    "Colombia: how much natural forest existed in 2020?",
])
async def test_combines_natural_forest_classes(query, natural_lands_state, run_insights, judge):
    """Natural forest questions should combine classes 2, 5, 8, 9."""
    result = await run_insights(query, natural_lands_state)

    verdict = await judge(
        query=query,
        rubric="""
        1. The output should combine natural forest, mangrove, natural peat forest,
           and wetland natural forest into one "natural forest" total — either as a
           single combined value or by listing all four and summing them.
        2. The total natural forest area should include all four classes, not just one.
        3. The insight should mention that natural forest includes these sub-categories
           (mangrove, peat forest, wetland forest) or at least present the combined total.
        """,
        tool_output=result,
    )

    assert verdict.passed, f"FAIL [{query[:50]}]: {verdict.comment}"
