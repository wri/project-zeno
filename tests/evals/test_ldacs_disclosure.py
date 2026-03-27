"""
Eval: LDACS citation and temporal caveat
Verifies that LDACS is named and its temporal limitations are disclosed
whenever driver breakdown data is shown.
"""

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


RUBRIC_NAMED = """
The response MUST mention LDACS (or Land Disturbance Alert Classification System)
by name. It should explain that LDACS classifies alert drivers.
The response must not present driver classes without attribution.
"""

RUBRIC_TEMPORAL = """
The response MUST include a caveat that LDACS may not have classified alerts
for the most recent period, and that 'Unclassified' alerts reflect this
assessment gap rather than an unknown driver.
"""


@pytest.mark.asyncio
async def test_ldacs_named_in_driver_response(dist_alert_state, run_insights, judge):
    query = "What are the main drivers of vegetation disturbance in DRC from June to November 2024? How is the driver classification done?"
    tool_output = await run_insights(query, dist_alert_state)
    verdict = await judge(query, RUBRIC_NAMED, tool_output)
    assert verdict.passed, verdict.comment


@pytest.mark.asyncio
async def test_ldacs_unclassified_explained(dist_alert_state, run_insights, judge):
    query = (
        "Show me a breakdown of disturbance drivers in DRC for 2024. "
        "Why is such a large proportion unclassified?"
    )
    tool_output = await run_insights(query, dist_alert_state)
    verdict = await judge(query, RUBRIC_TEMPORAL, tool_output)
    assert verdict.passed, verdict.comment
