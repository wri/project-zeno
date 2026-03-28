"""
Eval: TCL drivers dataset not used for annual/trend queries.
Verifies the response refuses to produce a timeseries from drivers data
and correctly explains the limitation.
"""

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


RUBRIC_NO_TIMESERIES = """
The response MUST NOT present the driver data as a year-by-year breakdown.
It should clearly state that the drivers dataset covers the aggregate period
2001-2024 only and cannot show annual trends.
If a timeseries was requested, the response should suggest using the Tree Cover
Loss dataset instead.
"""

RUBRIC_DEFAULT_RANGE = """
When no date range is specified and drivers data is shown, the response MUST
use the full 2001-2024 range and must NOT assume a shorter default range such
as 2001-2023.
"""


@pytest.mark.asyncio
async def test_driver_dataset_refuses_annual_query(tcl_driver_state, run_insights, judge):
    query = "Show me deforestation trends by driver for Colombia over the past 5 years."
    tool_output = await run_insights(query, tcl_driver_state)
    verdict = await judge(query, RUBRIC_NO_TIMESERIES, tool_output)
    assert verdict.passed, verdict.comment


@pytest.mark.asyncio
async def test_driver_dataset_uses_full_range_by_default(tcl_driver_state, run_insights, judge):
    query = "What are the main drivers of tree cover loss in Indonesia?"
    tool_output = await run_insights(query, tcl_driver_state)
    verdict = await judge(query, RUBRIC_DEFAULT_RANGE, tool_output)
    assert verdict.passed, verdict.comment
