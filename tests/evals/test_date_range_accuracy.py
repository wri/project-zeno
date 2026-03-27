"""
Eval: Stated dataset date ranges match fixture data, not memorised values.
"""

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

RUBRIC_GRASSLAND_DATES = """
The fixture data covers grassland extent from 2000 to 2022. The response must
state that data is available up to 2022 (not 2023 or any later date). It must
not report figures for years beyond 2022.
"""

RUBRIC_NO_ASSUMED_YEAR = """
The user did not specify a year. The response must NOT state or imply that
the user requested a specific year (e.g. "as requested for 2023"). It should
instead describe the full period covered by the data returned.
"""


@pytest.mark.asyncio
async def test_grassland_dates_match_fixture(grasslands_state, run_insights, judge):
    query = "What is the grassland extent in Kenya up to the latest available year?"
    tool_output = await run_insights(query, grasslands_state)
    verdict = await judge(query, RUBRIC_GRASSLAND_DATES, tool_output)
    assert verdict.passed, verdict.comment


@pytest.mark.asyncio
async def test_no_assumed_year_in_tcl_response(tcl_state, run_insights, judge):
    query = "Show me tree cover loss data for Pará, Brazil."
    tool_output = await run_insights(query, tcl_state)
    verdict = await judge(query, RUBRIC_NO_ASSUMED_YEAR, tool_output)
    assert verdict.passed, verdict.comment
