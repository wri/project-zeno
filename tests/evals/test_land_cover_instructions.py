"""
Eval cases for Global Land Cover (dataset 1) tiered instructions.

Fixture data: Brazil land cover transitions 2015→2024.
"""

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


# ---------------------------------------------------------------------------
# Behavior 1: Table for change/transition questions
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    "What land cover changes happened in Brazil between 2015 and 2024?",
    "Show land cover transitions in Brazil",
    "How did land cover change in Brazil from 2015 to 2024?",
    "Brazil land cover transition matrix",
    "Which land cover classes changed the most in Brazil?",
    "Show me what tree cover turned into in Brazil 2015-2024",
    "What replaced tree cover in Brazil over the past decade?",
    "Land cover class transitions in Brazil — table please",
    "break down the land cover changes in brazil",
    "How much tree cover became cropland in Brazil?",
    "What did short vegetation change into in Brazil?",
    "Brazil: all land cover transitions from 2015 to 2024",
    "Summarize land cover change for Brazil in a table",
    "which classes gained and lost area in Brazil?",
    "List every land cover transition in Brazil between 2015 and 2024",
])
async def test_table_for_transitions(query, land_cover_state, run_insights, judge):
    """Change questions must produce a table with start/end class columns."""
    result = await run_insights(query, land_cover_state)

    verdict = await judge(
        query=query,
        rubric="""
        1. The output must be a "table" (not pie, bar, line, or area chart).
        2. The table must include columns for the starting land cover class AND
           the ending land cover class (e.g., land_cover_class_start, land_cover_class_end).
        3. The table must include an area column (hectares or similar).
        """,
        tool_output=result,
    )

    assert verdict.passed, f"FAIL [{query[:50]}]: {verdict.comment}"


# ---------------------------------------------------------------------------
# Behavior 2: Pie chart for 2024 composition (snapshot)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    "What is the land cover composition of Brazil in 2024?",
    "Show me the breakdown of land cover types in Brazil",
    "Brazil land cover distribution 2024",
    "How much of Brazil is cropland vs tree cover in 2024?",
    "Pie chart of land cover in Brazil",
    "Current land cover makeup of Brazil",
    "What are the proportions of each land class in Brazil?",
    "land cover snapshot for Brazil",
    "Show the area of each land cover class in Brazil for 2024",
    "Brazil: how is the land divided among cover types?",
    "Breakdown of Brazil by land cover category",
    "How much tree cover, cropland, and built-up land does Brazil have?",
    "land cover pie chart for Brazil 2024",
    "proportional area of each land cover type in Brazil",
    "Brazil land cover areas by class — show as a chart",
])
async def test_pie_chart_for_composition(query, land_cover_state, run_insights, judge):
    """Composition/snapshot questions must produce a pie chart for 2024."""
    result = await run_insights(query, land_cover_state)

    verdict = await judge(
        query=query,
        rubric="""
        1. The chart type must be "pie".
        2. Each slice/segment should represent a different land cover class.
        3. The values should represent area (hectares) or proportion.
        """,
        tool_output=result,
    )

    assert verdict.passed, f"FAIL [{query[:50]}]: {verdict.comment}"


# ---------------------------------------------------------------------------
# Behavior 3: Refuses annual timeseries
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    "Show me annual land cover change in Brazil from 2015 to 2024",
    "Year-by-year land cover trends in Brazil",
    "How did cropland area change each year in Brazil?",
    "Plot land cover change over time for Brazil — yearly",
    "Annual tree cover area in Brazil 2015-2024",
    "Monthly land cover dynamics in Brazil",
    "Timeseries of land cover in Brazil",
    "Show me how cropland grew year by year in Brazil",
    "what was the land cover in brazil in 2018?",
    "land cover trend line for Brazil 2015-2024",
    "how did tree cover area change annually in Brazil?",
    "quarterly land cover changes in Brazil",
    "Brazil land cover each year from 2015 to 2024",
    "show the trajectory of built-up land in Brazil",
    "2016 vs 2020 vs 2024 land cover in Brazil",
])
async def test_refuses_annual_timeseries(query, land_cover_state, run_insights, judge):
    """Must indicate data only has 2015 and 2024 snapshots, not annual timeseries."""
    result = await run_insights(query, land_cover_state)

    if result["refused"]:
        return

    verdict = await judge(
        query=query,
        rubric="""
        1. The output must indicate that this dataset only has 2015 and 2024 snapshots,
           NOT annual data — it cannot show year-by-year trends.
        2. This indication can appear in the insight text, chart title, or tool message.
        3. If a chart is produced, it must NOT show multiple intermediate years between
           2015 and 2024.
        """,
        tool_output=result,
    )

    assert verdict.passed, f"FAIL [{query[:50]}]: {verdict.comment}"


# ---------------------------------------------------------------------------
# Behavior 4: Combines cropland + cultivated grassland for agriculture
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    "How much agricultural land is in Brazil?",
    "What area of Brazil is used for agriculture?",
    "Show me total agricultural area in Brazil",
    "Brazil agricultural land cover area",
    "How much farmland does Brazil have?",
    "Total area under agricultural use in Brazil",
    "What fraction of Brazil is agriculture?",
    "brazil farming area 2024",
    "show agricultural land in brazil — combined",
    "How much of Brazil is used for farming or grazing?",
    "Agricultural extent in Brazil",
    "What is the total area of cropland and pasture in Brazil?",
    "brazil agriculture breakdown",
    "How large is Brazil's agricultural footprint?",
    "farming and grazing land in Brazil — total area",
])
async def test_combines_agriculture(query, land_cover_state, run_insights, judge):
    """Agriculture questions should combine cropland + cultivated grassland."""
    result = await run_insights(query, land_cover_state)

    verdict = await judge(
        query=query,
        rubric="""
        1. The output should combine "cropland" and "cultivated grassland" when
           discussing agricultural area — either as a single combined value or
           by showing both and noting they together represent agriculture.
        2. The output should NOT show only cropland while ignoring cultivated
           grassland when the user asks about "agriculture" or "farming" broadly.
        """,
        tool_output=result,
    )

    assert verdict.passed, f"FAIL [{query[:50]}]: {verdict.comment}"
