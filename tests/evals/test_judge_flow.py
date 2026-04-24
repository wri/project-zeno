"""Pytest entrypoint for the eval judge flow.

These tests intentionally exercise `tests.evals.judge` via fixtures defined
in `tests/evals/conftest.py`.
"""


async def test_judge_flow_smoke(run_insights, judge, ghg_flux_state):
    """Run generate_insights + LLM judge and validate response shape."""
    query = "Brazil forest emissions and removals"
    rubric = """
    - Use a split/diverging bar chart for emissions vs removals.
    - Mention source/sink terminology in the explanation.
    """

    tool_output = await run_insights(query, ghg_flux_state)
    verdict = await judge(query, rubric, tool_output)

    assert isinstance(verdict.passed, bool)
    assert isinstance(verdict.comment, str)
    assert isinstance(verdict.requirements, list)
    assert verdict.judge_raw_response
