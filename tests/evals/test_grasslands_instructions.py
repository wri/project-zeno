"""
Eval cases for Natural/Semi-Natural Grasslands (dataset 2) tiered instructions.

Fixture data: Kenya grassland extent 2000-2022.
"""

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


# ---------------------------------------------------------------------------
# Behavior 1: Bar or line chart for area over time
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    "Show grassland area over time in Kenya",
    "How has natural grassland extent changed in Kenya from 2000 to 2022?",
    "Kenya grassland area trend",
    "Plot natural/semi-natural grassland area in Kenya by year",
    "Annual grassland extent in Kenya — chart it",
    "grassland area in Kenya over time",
    "How much grassland does Kenya have each year?",
    "Kenya: natural grassland trend 2000-2022",
    "Show me the change in grassland area in Kenya",
    "is Kenya losing grasslands? show the trend",
    "Natural grassland hectares in Kenya per year",
    "chart of grassland extent in Kenya 2000 through 2022",
    "Trend in natural/semi-natural grassland for Kenya",
    "How much grassland has Kenya lost since 2000?",
    "Kenya grassland trajectory over 22 years",
])
async def test_bar_or_line_for_trend(query, grasslands_state, run_insights, judge):
    """Area over time must use bar or line chart."""
    result = await run_insights(query, grasslands_state)

    verdict = await judge(
        query=query,
        rubric="""
        1. The chart type must be "bar" or "line".
        2. The x-axis should represent years.
        3. The y-axis should represent area in hectares.
        4. The data should show a temporal progression with multiple years.
        """,
        tool_output=result,
    )

    assert verdict.passed, f"FAIL [{query[:50]}]: {verdict.comment}"


# ---------------------------------------------------------------------------
# Behavior 2: Gain does NOT equal restoration
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    "How much grassland was restored in Kenya?",
    "Show grassland restoration in Kenya over time",
    "What area of grassland was restored in Kenya since 2000?",
    "Kenya grassland recovery and restoration",
    "grassland restoration trends in Kenya",
    "Has Kenya restored any natural grassland?",
    "show me the restoration of grasslands in Kenya",
    "How successful has grassland restoration been in Kenya?",
    "Kenya grassland gains — is this restoration?",
    "area of grassland restored per year in Kenya",
    "grassland regeneration in Kenya",
    "How much natural grassland has Kenya gained back?",
    "Kenya: restored grassland area",
    "What fraction of lost grassland was restored in Kenya?",
    "grassland recovery statistics for Kenya",
])
async def test_gain_not_restoration(query, grasslands_state, run_insights, judge):
    """Must NOT describe gains as 'restoration' without qualification."""
    result = await run_insights(query, grasslands_state)

    verdict = await judge(
        query=query,
        rubric="""
        1. The insight text must NOT use the term "restoration" to describe grassland
           gains WITHOUT qualifying it — gains may represent land abandonment, invasive
           species, woody encroachment, or temporary regrowth.
        2. If "restoration" is mentioned, it must include a caveat or warning that gain
           does not necessarily equal restoration.
        3. Terms like "gain", "increase", or "expansion" are acceptable without caveats.
        """,
        tool_output=result,
    )

    assert verdict.passed, f"FAIL [{query[:50]}]: {verdict.comment}"


# ---------------------------------------------------------------------------
# Behavior 3: Excludes zero/missing area rows
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    "Show grassland area for Kenya in each year",
    "Natural grassland extent in Kenya 2000-2022",
    "Kenya grassland data — all years",
    "Display all grassland area values for Kenya",
    "chart grassland area in Kenya per year",
    "Kenya natural grassland area complete dataset",
    "every year of grassland data for Kenya",
    "full time series of grassland area in Kenya",
    "Show all years of natural grassland extent for Kenya",
    "Kenya grassland hectares 2000 to 2022 — bar chart",
    "plot every year of grassland for Kenya",
    "annual natural grassland area in Kenya — show all",
    "complete grassland record for Kenya",
    "Kenya: grassland extent each year from 2000 to 2022",
    "all the grassland data for Kenya, yearly",
])
async def test_excludes_zero_area(query, grasslands_state, run_insights, judge):
    """Chart data should not include rows with area = 0."""
    result = await run_insights(query, grasslands_state)

    verdict = await judge(
        query=query,
        rubric="""
        1. The chart data must NOT include any row where area_ha = 0 or is missing/null.
        2. All data points shown should have positive, non-zero area values.
        3. The chart should display a temporal progression of grassland area.
        """,
        tool_output=result,
    )

    assert verdict.passed, f"FAIL [{query[:50]}]: {verdict.comment}"
