"""
Eval cases for Tree Cover (dataset 7) tiered instructions.

Fixture data: DRC tree cover canopy density bins for year 2000.
"""

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


# ---------------------------------------------------------------------------
# Behavior 1: Bar or pie chart for binned tree cover
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    "Show tree cover density distribution in the Democratic Republic of Congo",
    "How is tree cover distributed by canopy density in DRC?",
    "DRC tree cover by density bin",
    "Bar chart of tree cover extent in DRC by canopy density",
    "Tree cover density breakdown for DRC",
    "Show the area of each canopy density class in DRC",
    "DRC: tree cover area by percent canopy cover",
    "How much of DRC has dense tree cover vs sparse?",
    "tree cover distribution in DRC",
    "chart tree cover by canopy density for DRC",
    "DRC tree cover breakdown by percentage brackets",
    "What are the canopy density classes in DRC and their areas?",
    "tree cover density bins for DRC — bar chart",
    "canopy cover distribution in DRC year 2000",
    "How is DRC's tree cover distributed across density levels?",
])
async def test_bar_or_pie_for_density(query, tree_cover_state, run_insights, judge):
    """Must use bar or pie chart for canopy density bins."""
    result = await run_insights(query, tree_cover_state)

    verdict = await judge(
        query=query,
        rubric="""
        1. The chart type must be "bar" or "pie".
        2. The data should show canopy density bins/brackets on one axis and area
           on the other.
        3. Values should represent area in hectares.
        """,
        tool_output=result,
    )

    assert verdict.passed, f"FAIL [{query[:50]}]: {verdict.comment}"


# ---------------------------------------------------------------------------
# Behavior 2: Uses "tree cover" not "forest" (without primary/IFL layer)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    "How much forest is in the DRC?",
    "Show forest area in the Democratic Republic of Congo",
    "DRC forest extent",
    "forest coverage in the DRC",
    "How much of the DRC is forested?",
    "total forest area in DRC",
    "DRC forest density breakdown",
    "show me the forests of the DRC",
    "how big are DRC's forests?",
    "forest distribution in the DRC by density",
    "DRC forest cover in 2000",
    "what percentage of DRC is forest?",
    "DRC forest extent breakdown",
    "area of forest in DRC by canopy density",
    "how dense are DRC's forests?",
])
async def test_uses_tree_cover_not_forest(query, tree_cover_state, run_insights, judge):
    """Must use 'tree cover' not 'forest' without primary/IFL variable active."""
    result = await run_insights(query, tree_cover_state)

    verdict = await judge(
        query=query,
        rubric="""
        1. The insight text must use "tree cover" (or close variants like "canopy cover",
           "tree canopy") as the primary term.
        2. The insight text should NOT use the unqualified term "forest" or "forested" to
           describe the results, UNLESS it is noting that "tree cover" includes plantations
           and is not limited to natural forest.
        3. A clarification like "tree cover includes both forests and plantations" is acceptable.
        """,
        tool_output=result,
    )

    assert verdict.passed, f"FAIL [{query[:50]}]: {verdict.comment}"


# ---------------------------------------------------------------------------
# Behavior 3: Excludes zero area bin
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    "Show all tree cover density classes in DRC",
    "Complete tree cover breakdown for DRC",
    "DRC tree cover data — every density bin",
    "all canopy density categories for DRC",
    "full breakdown of tree cover in DRC",
    "Tree cover area for every density bracket in DRC",
    "DRC: all canopy cover bins with area",
    "complete tree cover distribution for DRC",
    "show every tree cover density class for DRC",
    "DRC canopy density — all categories",
    "tree cover by density — include everything for DRC",
    "exhaustive tree cover density data for DRC",
    "DRC tree cover: 0% through 100% bins",
    "all density brackets for DRC tree cover",
    "full tree cover density profile for DRC",
])
async def test_excludes_zero_area(query, tree_cover_state, run_insights, judge):
    """Must exclude the 0% canopy density bin (area = 0)."""
    result = await run_insights(query, tree_cover_state)

    verdict = await judge(
        query=query,
        rubric="""
        1. The chart data must NOT include a row/segment where area_ha = 0.
        2. The 0% canopy density bin should be excluded from the visualization.
        3. The output may note that zero-area bins were excluded.
        """,
        tool_output=result,
    )

    assert verdict.passed, f"FAIL [{query[:50]}]: {verdict.comment}"


# ---------------------------------------------------------------------------
# Behavior 4: Refuses change over time
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    "How has tree cover changed in DRC over time?",
    "Show me the trend in DRC tree cover",
    "Has DRC lost tree cover since 2000?",
    "Tree cover change in DRC 2000-2024",
    "annual tree cover in DRC",
    "DRC tree cover loss trend",
    "is DRC losing trees? show the trend",
    "timeseries of tree cover in DRC",
    "compare tree cover in DRC 2000 vs 2020",
    "How much tree cover did DRC lose each year?",
    "year by year tree cover for DRC",
    "DRC tree cover trajectory",
    "tree cover change rate in DRC",
    "how fast is DRC losing tree cover?",
    "DRC: tree cover over the years",
])
async def test_refuses_change_over_time(query, tree_cover_state, run_insights, judge):
    """Must refuse change/trend — this is a year 2000 snapshot only."""
    result = await run_insights(query, tree_cover_state)

    if result["refused"]:
        return

    verdict = await judge(
        query=query,
        rubric="""
        1. The output must indicate that this dataset is a single-year (2000) snapshot
           and cannot show change over time.
        2. The output should suggest using Tree Cover Loss or Tree Cover Gain datasets
           for change analysis.
        3. The chart data must NOT show multiple years or temporal progression.
        """,
        tool_output=result,
    )

    assert verdict.passed, f"FAIL [{query[:50]}]: {verdict.comment}"
