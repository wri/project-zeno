"""
Eval: Response language matches query language.
Verifies that a non-English query produces a fully non-English response,
including dataset descriptions and cautions.
"""

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


RUBRIC_FR = """
The query was written in French. The response must be in French.
Evaluate ONLY the insight text, cautions, and dataset descriptions — i.e.
the natural-language prose shown to the user.
Ignore programmatic / technical artefacts: chart_type enum values (e.g. "bar",
"line"), CSV column header keys (e.g. "area_ha", "perte_ha"), and code blocks.
There must be no English *sentences* in the prose portions of the response.
"""

RUBRIC_DE = """
The query was written in German. The response must be in German.
Evaluate ONLY the insight text, cautions, and dataset descriptions — i.e.
the natural-language prose shown to the user.
Ignore programmatic / technical artefacts: chart_type enum values (e.g. "bar",
"grouped-bar"), CSV column header keys (e.g. "area_ha", "month"), and code blocks.
There must be no English *sentences* in the prose portions of the response.
"""


@pytest.mark.asyncio
async def test_french_query_french_response(tcl_state, run_insights, judge):
    query = "Quelle est la superficie de la perte de couvert forestier au Brésil entre 2015 et 2022 ?"
    tool_output = await run_insights(query, tcl_state)
    verdict = await judge(query, RUBRIC_FR, tool_output)
    assert verdict.passed, verdict.comment


@pytest.mark.asyncio
async def test_german_query_german_response(dist_alert_state, run_insights, judge):
    query = "Zeige mir die Vegetationsstörungen in der Demokratischen Republik Kongo von Juni bis November 2024."
    tool_output = await run_insights(query, dist_alert_state)
    verdict = await judge(query, RUBRIC_DE, tool_output)
    assert verdict.passed, verdict.comment
