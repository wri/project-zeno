"""
Eval cases for DIST-ALERT (dataset 0) tiered instructions.

Each behavior is tested with ~15 prompt phrasings for robustness.
Tests call real Gemini Flash + Haiku judge — no LLM mocks.

Note: Fixture data is for the Democratic Republic of Congo, so all queries
target that region. Different phrasings test instruction-following,
not dataset selection.
"""

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


# ---------------------------------------------------------------------------
# Behavior 1: Pie chart for driver distribution
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    # Original 3
    "What are the main causes of disturbance in the Democratic Republic of Congo?",
    "Show the driver breakdown of ecosystem disturbance alerts in DRC",
    "Distribution of disturbance types in the Democratic Republic of Congo",
    # Formal
    "Provide a proportional breakdown of disturbance alert drivers for the Democratic Republic of Congo",
    "Categorize the DIST-ALERT data by driver classification for DRC",
    "What is the distribution of disturbance causes across driver classes in the DRC?",
    # Casual
    "disturbance causes in DRC",
    "what's causing the alerts in DRC? show a breakdown",
    "DRC alert drivers — pie chart",
    # Variant terminology
    "Show me the proportion of each disturbance type in DRC",
    "Which driver dominates disturbance in the DRC?",
    "Rank the alert causes by area in the Democratic Republic of Congo",
    # Edge cases
    "What's the biggest driver of vegetation disturbance in DRC?",
    "DRC: how much area does each disturbance type cover?",
    "Break down the DRC alerts into categories",
])
async def test_pie_chart_for_driver_distribution(query, dist_alert_state, run_insights, judge):
    """Driver distribution should be shown as a pie chart."""
    result = await run_insights(query, dist_alert_state)

    verdict = await judge(
        query=query,
        rubric="""
        1. The chart type must be "pie".
        2. Each segment/slice should represent a different driver or disturbance type
           (e.g., Conversion, Fire-related, Cropland dynamics, Water-related).
        3. The values should represent area (hectares) or a count metric.
        """,
        tool_output=result,
    )

    assert verdict.passed, f"FAIL [{query[:50]}]: {verdict.comment}"


# ---------------------------------------------------------------------------
# Behavior 2: Grouped bar for seasonal patterns
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    # Original 3
    "Show monthly disturbance patterns by driver in DRC from June to November 2024",
    "Seasonal breakdown of alert types by month in the Democratic Republic of Congo",
    "Compare disturbance drivers across months in DRC, show as grouped bars",
    # Formal
    "Display monthly variation of disturbance alerts disaggregated by driver class for DRC, June-November 2024",
    "Provide a month-by-month comparison of each disturbance driver in the Democratic Republic of Congo",
    "How do the different disturbance drivers vary month to month in DRC?",
    # Casual
    "monthly drivers in DRC grouped by type",
    "alerts by month and driver for DRC",
    "DRC: each driver per month",
    # Variant phrasing
    "Which months had the most conversion vs fire in DRC?",
    "Show how each driver type fluctuates month to month in DRC",
    "Compare all driver types side by side for each month in DRC",
    # Edge cases
    "Monthly breakdown of alerts by cause in DRC, June-Nov 2024",
    "DRC alert drivers month by month — I want to see them grouped",
    "Side-by-side monthly comparison of DRC disturbance drivers",
])
async def test_grouped_bar_for_seasonal_patterns(query, dist_alert_state, run_insights, judge):
    """Seasonal patterns by driver should use grouped bar chart."""
    result = await run_insights(query, dist_alert_state)

    verdict = await judge(
        query=query,
        rubric="""
        1. The chart type must be "grouped-bar".
        2. The x-axis should represent time periods (months).
        3. The bars should be grouped by driver/disturbance type, with different
           drivers shown side-by-side for each month.
        4. The y-axis should represent area in hectares or a count metric.
        """,
        tool_output=result,
    )

    assert verdict.passed, f"FAIL [{query[:50]}]: {verdict.comment}"


# ---------------------------------------------------------------------------
# Behavior 3: Line chart for trends over time
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    # Original 3
    "Show the trend in disturbance alerts in the Democratic Republic of Congo over time",
    "How have ecosystem alerts changed month to month in DRC?",
    "Plot the alert trend over time for DRC, June to November 2024",
    # Formal
    "Display the temporal trend of total disturbance alert area for the DRC from June to November 2024",
    "Provide a time series of disturbance alert volumes for the Democratic Republic of Congo",
    "What is the overall trend in vegetation disturbance alerts in DRC over recent months?",
    # Casual
    "alert trend DRC over time",
    "how are alerts trending in DRC?",
    "DRC disturbance trend line",
    # Variant phrasing
    "Are disturbance alerts increasing or decreasing in DRC?",
    "Total disturbed area per month in DRC — show as a trend",
    "Plot total alert area over time for DRC",
    # Edge cases
    "Is the disturbance situation getting worse or better in DRC?",
    "Month-over-month change in DRC alert area",
    "DRC: overall alert trend from June to November 2024",
])
async def test_line_chart_for_trends(query, dist_alert_state, run_insights, judge):
    """Temporal trends should use line chart."""
    result = await run_insights(query, dist_alert_state)

    verdict = await judge(
        query=query,
        rubric="""
        1. The chart type must be "line".
        2. The x-axis should represent time (months or dates).
        3. The y-axis should represent area in hectares, alert count, or similar metric.
        4. The data should show a temporal progression, not categories.
        """,
        tool_output=result,
    )

    assert verdict.passed, f"FAIL [{query[:50]}]: {verdict.comment}"
