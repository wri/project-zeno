"""
Eval: GNW does not suggest unavailable datasets in next steps.
Verifies that follow-up recommendations only reference datasets
that exist within the GNW platform.
"""

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

UNAVAILABLE_DATASETS = [
    "GLAD alert",
    "PRODES",
    "Hansen annual",
    "Global Forest Change",
    "FORMA",
    "Terra-i",
]

RUBRIC = """
The response must NOT recommend or reference any dataset or monitoring system
that is not available within Global Nature Watch. Specifically, it must not
mention: GLAD alerts, PRODES, Hansen annual tiles (outside the standard TCL
pipeline), FORMA, Terra-i, or any other external forest monitoring system as
a suggested next step. All recommended next steps must use datasets available
in the GNW platform.
"""


@pytest.mark.asyncio
async def test_next_steps_only_reference_gnw_datasets(tcl_state, run_insights, judge):
    query = (
        "Which regions in Pará, Brazil should I prioritise for biodiversity monitoring? "
        "What should I look at next?"
    )
    tool_output = await run_insights(query, tcl_state)
    verdict = await judge(query, RUBRIC, tool_output)
    assert verdict.passed, verdict.comment
