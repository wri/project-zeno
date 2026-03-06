"""
Eval cases for Forest GHG Net Flux (dataset 6) tiered instructions.

Fixture data: Brazil total emissions, removals, net flux (2001-2024 aggregate).
"""

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


# ---------------------------------------------------------------------------
# Behavior 1: Split/diverging bar chart
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    "Show the forest carbon flux for Brazil",
    "What is the net greenhouse gas flux from forests in Brazil?",
    "Brazil forest emissions and removals",
    "Display forest GHG net flux for Brazil",
    "Chart Brazil's forest carbon balance",
    "forest carbon flux in Brazil — emissions vs removals",
    "show me the ghg flux for Brazil forests",
    "Brazil forest greenhouse gas balance",
    "How much carbon do Brazil's forests emit vs absorb?",
    "forest emissions and sequestration in Brazil",
    "Brazil: net flux of greenhouse gases from forests",
    "chart forest carbon emissions and removals for Brazil",
    "Brazil forest carbon source or sink?",
    "GHG balance of Brazilian forests",
    "show the carbon budget for Brazil's forests",
])
async def test_split_bar_chart(query, ghg_flux_state, run_insights, judge):
    """Must show split/diverging bar chart with emissions positive and removals negative."""
    result = await run_insights(query, ghg_flux_state)

    verdict = await judge(
        query=query,
        rubric="""
        1. The chart type must be "bar" (a split or diverging bar chart).
        2. The chart data should show emissions as positive values and removals as negative
           values (or clearly separate them into two categories).
        3. Values should be in MgCO2e or similar GHG units.
        """,
        tool_output=result,
    )

    assert verdict.passed, f"FAIL [{query[:50]}]: {verdict.comment}"


# ---------------------------------------------------------------------------
# Behavior 2: Refuses timeseries / annual values
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    "Show annual forest carbon emissions for Brazil 2001-2024",
    "Forest GHG flux trend over time in Brazil",
    "How have forest emissions changed year by year in Brazil?",
    "Year-by-year carbon flux from Brazil's forests",
    "annual removals from Brazilian forests",
    "Plot forest emissions per year for Brazil",
    "timeseries of forest carbon flux in Brazil",
    "How did forest carbon balance change annually in Brazil?",
    "Brazil forest flux 2005 vs 2010 vs 2020",
    "monthly forest emissions in Brazil",
    "trend in forest greenhouse gas flux for Brazil",
    "has Brazil's forest carbon sink improved over time?",
    "annual forest carbon sequestration in Brazil 2001-2024",
    "yearly emissions from deforestation in Brazil",
    "show the trajectory of forest carbon flux in Brazil",
])
async def test_refuses_timeseries(query, ghg_flux_state, run_insights, judge):
    """Must refuse annual/timeseries — data is total over 2001-2024 period."""
    result = await run_insights(query, ghg_flux_state)

    if result["refused"]:
        return

    verdict = await judge(
        query=query,
        rubric="""
        1. The output must indicate that this data represents a TOTAL over the
           model period 2001-2024, NOT annual values or a timeseries.
        2. The chart data must NOT show year-by-year values or temporal progression.
        3. The insight text should mention that to get annual average, divide by 24.
        """,
        tool_output=result,
    )

    assert verdict.passed, f"FAIL [{query[:50]}]: {verdict.comment}"


# ---------------------------------------------------------------------------
# Behavior 3: Uses net sink / net source terminology
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    "Is Brazil's forest a carbon source or sink?",
    "What is the net carbon balance of Brazil's forests?",
    "Are Brazil's forests absorbing or emitting more carbon?",
    "Brazil forest net greenhouse gas flux",
    "Is Brazil a net emitter or absorber of forest carbon?",
    "net carbon flux from forests in Brazil",
    "do Brazil's forests emit or sequester more carbon?",
    "Brazil: are forests net positive or negative for climate?",
    "forest carbon balance for Brazil — source or sink?",
    "Is the Brazilian forest a net source?",
    "what's the sign of forest flux in Brazil?",
    "Brazil forest: emitter or absorber?",
    "net flux direction for Brazil's forests",
    "is Brazil gaining or losing forest carbon?",
    "overall carbon balance of forests in Brazil",
])
async def test_uses_sink_source_terminology(query, ghg_flux_state, run_insights, judge):
    """Must use 'net sink' or 'net source' terminology."""
    result = await run_insights(query, ghg_flux_state)

    verdict = await judge(
        query=query,
        rubric="""
        1. The insight text must use the term "net sink" (for net-negative flux, where
           removals exceed emissions) or "net source" (for net-positive flux, where
           emissions exceed removals).
        2. The terminology must correctly match the data — positive net flux = "net source",
           negative net flux = "net sink".
        3. The term "net sink" or "net source" must appear at least once in the insight.
        """,
        tool_output=result,
    )

    assert verdict.passed, f"FAIL [{query[:50]}]: {verdict.comment}"
