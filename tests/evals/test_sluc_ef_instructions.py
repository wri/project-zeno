"""
Eval cases for sLUC Emission Factors (dataset 9) tiered instructions.

Fixture data: Brazil crop emission factors for 5 crops in 2024.
"""

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


# ---------------------------------------------------------------------------
# Behavior 1: Pie chart for gas type proportions
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    "Show the emissions breakdown by gas type for soybean in Brazil",
    "What proportion of soybean emissions is CO2 vs CH4 vs N2O in Brazil?",
    "Soybean emissions by gas type in Brazil 2024 — pie chart",
    "Proportional GHG breakdown for soybean production in Brazil",
    "How much of Brazil's soybean deforestation emissions is CO2?",
    "gas type breakdown for soybean emissions in Brazil",
    "Brazil soybean: CO2 vs CH4 vs N2O emissions",
    "emission composition by gas for soybean in Brazil",
    "pie chart of gas contributions for Brazil soybean",
    "What gases make up soybean deforestation emissions in Brazil?",
    "Brazil soybean emissions — which gas dominates?",
    "proportional emissions by gas type for soybean, Brazil",
    "GHG composition of Brazil's soybean-related deforestation",
    "break down soybean emissions into CO2, CH4, N2O for Brazil",
    "gas type distribution for Brazil soybean 2024",
])
async def test_pie_for_gas_type(query, sluc_ef_state, run_insights, judge):
    """Gas type proportion must use pie chart."""
    result = await run_insights(query, sluc_ef_state)

    verdict = await judge(
        query=query,
        rubric="""
        1. The chart type must be "pie".
        2. Each slice should represent a different gas type (CO2, CH4, N2O).
        3. Values should represent emissions in tCO2e or proportions.
        """,
        tool_output=result,
    )

    assert verdict.passed, f"FAIL [{query[:50]}]: {verdict.comment}"


# ---------------------------------------------------------------------------
# Behavior 2: Table for multiple crops
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    "Compare emission factors for all crops in Brazil",
    "Show emission factors for soybean, oil palm, and cattle in Brazil",
    "Table of crop emission factors for Brazil",
    "What are the emission factors for different crops in Brazil?",
    "rank crops by emission factor in Brazil",
    "Brazil: emission factors for all agricultural crops",
    "compare soybean vs palm oil vs cocoa emission factors in Brazil",
    "list all crop emission factors for Brazil 2024",
    "which crop has the highest emission factor in Brazil?",
    "emission factor comparison across crops in Brazil",
    "table of EF for multiple crops in Brazil",
    "Brazil crop emission factors — show all",
    "sLUC emission factors by crop for Brazil",
    "compare the deforestation intensity of crops in Brazil",
    "all crop emission factors in Brazil — ranked",
])
async def test_table_for_multiple_crops(query, sluc_ef_state, run_insights, judge):
    """Multiple crop comparison must use a table."""
    result = await run_insights(query, sluc_ef_state)

    verdict = await judge(
        query=query,
        rubric="""
        1. The chart type must be "table".
        2. The table should list multiple crops with their emission factors.
        3. Values should include units (tCO2e per tonne or similar).
        """,
        tool_output=result,
    )

    assert verdict.passed, f"FAIL [{query[:50]}]: {verdict.comment}"


# ---------------------------------------------------------------------------
# Behavior 3: Refuses map request
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    "Show a map of soybean emission factors in Brazil",
    "Map the deforestation emissions for crops across Brazil",
    "Spatial distribution of crop emission factors in Brazil",
    "show me on a map where soybean emissions are highest in Brazil",
    "map of sLUC emission factors across Brazil",
    "geographic distribution of crop deforestation emissions in Brazil",
    "visualize emission factors spatially for Brazil",
    "where in Brazil are emission factors highest? show on map",
    "brazil emission factor heatmap by region",
    "plot emission factors on a map for Brazil",
    "spatial view of soybean deforestation emissions in Brazil",
    "map overlay of crop emissions across Brazilian states",
    "geographic breakdown of emission factors in Brazil",
    "show emission factor hotspots on a map for Brazil",
    "Brazil: spatial emission factor visualization",
])
async def test_refuses_map(query, sluc_ef_state, run_insights, judge):
    """Must refuse map requests — this is tabular data only."""
    result = await run_insights(query, sluc_ef_state)

    if result["refused"]:
        return

    verdict = await judge(
        query=query,
        rubric="""
        1. The output must indicate that this dataset is tabular data only and
           cannot be shown on a map.
        2. The output should NOT claim to provide spatial/geographic visualization.
        3. The output may still provide the data in table or chart form as an
           alternative.
        """,
        tool_output=result,
    )

    assert verdict.passed, f"FAIL [{query[:50]}]: {verdict.comment}"


# ---------------------------------------------------------------------------
# Behavior 4: Always includes units
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    "What is the emission factor for soybean in Brazil?",
    "Show soybean deforestation emissions in Brazil",
    "Brazil soybean emission factor 2024",
    "How much CO2 per tonne of soybean in Brazil?",
    "soybean emission factor for Brazil",
    "emissions per unit of soybean production in Brazil",
    "Brazil: soybean sLUC emission factor",
    "what's the deforestation footprint of soybeans in Brazil?",
    "soybean deforestation emission rate in Brazil",
    "carbon intensity of soybean in Brazil",
    "emission factor for soybean production, Brazil 2024",
    "how many tonnes of CO2 per tonne of soybean in Brazil?",
    "Brazil soybean: deforestation-linked emissions",
    "sLUC factor for Brazil soybean",
    "greenhouse gas intensity of Brazilian soy",
])
async def test_includes_units(query, sluc_ef_state, run_insights, judge):
    """Must include units: tCO2e for emissions, tonnes for production."""
    result = await run_insights(query, sluc_ef_state)

    verdict = await judge(
        query=query,
        rubric="""
        1. The insight text must include the unit "tCO2e" (or close variant like
           "tonnes of CO2 equivalent", "tCO₂e") when referencing emissions.
        2. If production volume is mentioned, it must include "tonnes" or "t" as the unit.
        3. Emission factors should be expressed with both numerator and denominator units
           (e.g., "tCO2e per tonne of product" or "tCO2e/t").
        """,
        tool_output=result,
    )

    assert verdict.passed, f"FAIL [{query[:50]}]: {verdict.comment}"
