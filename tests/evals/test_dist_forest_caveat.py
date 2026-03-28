"""
Eval: DIST-ALERT forest caveat
Verifies that when DIST alert data is presented for a forest-loss query,
the response includes a caveat that alerts cover all vegetation, not just forest.
"""

import pytest
from tests.evals.judge import run_generate_insights, judge_output

pytestmark = pytest.mark.asyncio(loop_scope="session")


RUBRIC = """
The response MUST include a caveat explaining that DIST-ALERT covers ALL
vegetation types and is not limited to forest. It should state that results
may include non-forest disturbances such as crop harvesting or grassland change.
The caveat must appear even if the analysis data looks plausible.
The response must NOT present the alert numbers as confirmed forest loss.
"""


@pytest.mark.asyncio
async def test_dist_forest_query_includes_vegetation_caveat(dist_alert_state, run_insights, judge):
    query = "How much forest was lost in the Democratic Republic of Congo in the last 6 months?"
    tool_output = await run_insights(query, dist_alert_state)
    verdict = await judge(query, RUBRIC, tool_output)
    assert verdict.passed, verdict.comment


@pytest.mark.asyncio
async def test_dist_deforestation_query_includes_caveat(dist_alert_state, run_insights, judge):
    query = "Show me deforestation alerts in DRC from June to November 2024."
    tool_output = await run_insights(query, dist_alert_state)
    verdict = await judge(query, RUBRIC, tool_output)
    assert verdict.passed, verdict.comment
