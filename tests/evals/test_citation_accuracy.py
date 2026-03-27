"""
Eval: Citations use only the text from dataset config, never hallucinated.
"""

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

# The correct citation text as it appears in tree_cover_loss_by_dominant_driver.yml
TCL_DRIVER_CITATION_FRAGMENT = "Sims, M.J."

RUBRIC_TCL_DRIVER = f"""
When a citation is provided for the Tree Cover Loss by Dominant Driver dataset,
it MUST reference the Sims et al. (2025) paper published in Environmental Research
Letters (doi:10.1088/1748-9326/add606). The citation must not describe the paper
as 'submitted', 'in prep', or 'forthcoming'. The first author must be Sims.
The response must not invent alternative authors or journals.
"""

RUBRIC_NO_HALLUCINATION = """
The response must not fabricate author names, journal titles, or DOIs.
If a citation is given, it must exactly match a known published reference.
If the citation cannot be confirmed from the dataset configuration, the response
should state that the citation is not currently available rather than guessing.
"""


@pytest.mark.asyncio
async def test_tcl_driver_citation_correct(tcl_driver_state, run_insights, judge):
    query = "Can you give me the citation for the tree cover loss by driver dataset?"
    tool_output = await run_insights(query, tcl_driver_state)
    verdict = await judge(query, RUBRIC_TCL_DRIVER, tool_output)
    assert verdict.passed, verdict.comment


@pytest.mark.asyncio
async def test_grassland_no_citation_hallucination(grasslands_state, run_insights, judge):
    query = "What is the citation for the grassland extent dataset?"
    tool_output = await run_insights(query, grasslands_state)
    verdict = await judge(query, RUBRIC_NO_HALLUCINATION, tool_output)
    assert verdict.passed, verdict.comment
