"""
Eval cases for Tree Cover Loss (dataset 4) tiered instructions.

Each behavior is tested with ~15 prompt phrasings for robustness.
Tests call real Gemini Flash + Haiku judge — no LLM mocks.

Note: Fixture data is for Pará, Brazil, so all queries target that region.
Different phrasings test instruction-following, not dataset selection.
"""

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


# ---------------------------------------------------------------------------
# Behavior 1: Separate charts for loss vs emissions
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    # Original 4
    "Show me tree cover loss and emissions in Pará, Brazil 2015-2022",
    "What was the deforestation and carbon impact in Pará last decade?",
    "TCL with GHG data for Pará, Brazil 2015-2022",
    "Forest loss area and CO2 emissions in Pará, Brazil",
    # Formal / technical
    "Provide annual tree cover loss in hectares together with associated GHG emissions in MgCO2e for Pará, Brazil, 2015-2022",
    "I need both the area of tree cover loss and the carbon dioxide equivalent emissions for Pará, Brazil between 2015 and 2022",
    # Casual / abbreviated
    "loss + emissions for Pará 2015-2022",
    "give me forest loss and carbon numbers for Pará Brazil",
    # Mixed phrasing
    "Plot hectares lost and MgCO2e on the same graph for Pará 2015-2022",
    "Can I see loss area alongside greenhouse gas emissions for Pará?",
    "Pará Brazil: tree cover loss area plus emissions data 2015-2022",
    # Variant terminology
    "Show CO2 emissions and canopy loss together for Pará",
    "How much carbon was released alongside forest loss in Pará 2015-2022?",
    "Pará deforestation area and associated carbon emissions",
    "Compare hectares lost with CO2e emitted in Pará, Brazil",
])
async def test_separate_charts_for_loss_and_emissions(query, tcl_state, run_insights, judge):
    """Must NOT mix area and emissions in one chart — separate visualizations."""
    result = await run_insights(query, tcl_state)

    verdict = await judge(
        query=query,
        rubric="""
        1. The chart data must NOT contain both area/hectares columns AND emissions/CO2/GHG columns
           in the same chart dataset. They must be in separate charts.
        2. If only one chart is produced, it must show EITHER area (hectares) OR emissions (MgCO2e),
           not both metrics together.
        3. The insight text should acknowledge both metrics exist but note they should be
           visualized separately.
        """,
        tool_output=result,
    )

    assert verdict.passed, f"FAIL [{query[:50]}]: {verdict.comment}"


# ---------------------------------------------------------------------------
# Behavior 2: Refuses intra-year / seasonal requests
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    # Original 4
    "Show me monthly tree cover loss in Pará, Brazil for 2020",
    "What's the seasonal pattern of deforestation in Pará?",
    "Break down tree cover loss by quarter in Pará, Brazil 2019",
    "Show me January through December tree cover loss for Pará",
    # Formal
    "Provide a monthly time series of tree cover loss for Pará, Brazil in 2021",
    "Could you display weekly forest loss data for Pará?",
    # Casual
    "monthly TCL for Pará 2020",
    "show me loss by month for Pará, Brazil",
    # Variant terminology
    "What months had the worst deforestation in Pará?",
    "Daily forest loss for Pará, Brazil in 2020",
    # Edge cases
    "Compare Q1 vs Q3 tree cover loss in Pará, Brazil 2020",
    "Which month in 2019 had peak forest loss in Pará?",
    "Seasonal deforestation breakdown for Pará 2020",
    "Show me the within-year pattern of canopy loss in Pará",
    "Is there a dry-season vs wet-season loss pattern in Pará, Brazil?",
])
async def test_refuses_intra_year_requests(query, tcl_state, run_insights, judge):
    """Must refuse or note that data is annual only — no monthly/weekly breakdown."""
    result = await run_insights(query, tcl_state)

    # If the tool itself refused (no chart data), that's a pass —
    # the code executor correctly declined to produce intra-year data
    if result["refused"]:
        return

    verdict = await judge(
        query=query,
        rubric="""
        1. The output must indicate that the data is annual only and cannot provide
           monthly, seasonal, or quarterly breakdowns.
        2. This indication can appear in the insight text, tool message, or chart title.
        3. If a chart is still produced, it must show annual data (by year), NOT monthly data.
        """,
        tool_output=result,
    )

    assert verdict.passed, f"FAIL [{query[:50]}]: {verdict.comment}"


# ---------------------------------------------------------------------------
# Behavior 3: Uses "tree cover loss" not "deforestation"
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    # Original 3
    "Show deforestation trends in Pará, Brazil 2015-2022",
    "How much forest was lost in Pará, Brazil over the last decade?",
    "Annual deforestation data for Pará, Brazil",
    # Formal
    "Provide an analysis of deforestation rates in Pará, Brazil from 2015 to 2022",
    "Quantify the annual area deforested in Pará, Brazil between 2015 and 2022",
    # Casual
    "how bad is the deforestation in Pará?",
    "deforestation stats for Pará, Brazil pls",
    # Variant terminology
    "forest destruction in Pará over time",
    "How much of Pará has been clearcut 2015-2022?",
    "Pará Brazil — show the logging and clearing data",
    # Edge cases — provocative terms
    "Chart the deforestation crisis in Pará, Brazil",
    "Razed forest area in Pará 2015-2022",
    "Show how much jungle was destroyed in Pará",
    "Pará, Brazil rainforest decimation stats",
    "Annual cleared area in Pará 2015 through 2022",
])
async def test_uses_tree_cover_loss_terminology(query, tcl_state, run_insights, judge):
    """Insight text must use 'tree cover loss', not 'deforestation'."""
    result = await run_insights(query, tcl_state)

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


# ---------------------------------------------------------------------------
# Behavior 4: Bar chart for yearly loss
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    # Original 3
    "Show me annual tree cover loss in Pará, Brazil from 2015 to 2022",
    "How much forest did Pará lose each year between 2015 and 2022?",
    "Yearly tree cover loss in Pará — chart it",
    # Formal
    "Display annual tree cover loss in hectares for Pará, Brazil, 2015 through 2022",
    "Provide a yearly breakdown of tree cover loss area for Pará, Brazil",
    # Casual
    "pará brazil tcl per year 2015-2022",
    "how much forest did Pará lose each year?",
    "annual loss in Pará, chart please",
    # Variant terminology
    "Annual deforestation data for Pará, Brazil 2015-2022 as a chart",
    "Year-by-year canopy loss in Pará 2015-2022",
    # Edge cases
    "Tree cover loss each year for Pará — visualize it",
    "Compare tree cover loss across years for Pará, Brazil (2015-2022)",
    "Pará, Brazil TCL 2015 2016 2017 2018 2019 2020 2021 2022",
    "Show the trend in annual tree cover loss for Pará, Brazil",
    "Bar chart of yearly forest loss in Pará from 2015 to 2022",
])
async def test_bar_chart_for_yearly_loss(query, tcl_state, run_insights, judge):
    """Must produce a bar chart with years on x-axis."""
    result = await run_insights(query, tcl_state)

    verdict = await judge(
        query=query,
        rubric="""
        1. The chart type must be "bar" (not "line", "pie", "area", or "table").
        2. The x-axis should represent years.
        3. The y-axis should represent area (hectares) or a similar area metric.
        """,
        tool_output=result,
    )

    assert verdict.passed, f"FAIL [{query[:50]}]: {verdict.comment}"
