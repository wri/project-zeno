import pytest

from tests.evals.fixture_data import TCL_US_STATES_STATE

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_tree_cover_loss_across_all_us_states_eval(
    run_insights, judge
):
    query = "Show me tree cover loss across all states in the United States"
    rubric = """
    The response should answer the user's request using the available state-level tree cover loss data.

    Requirements:
    - It should not refuse the request.
    - It should produce a chart suitable for comparing many U.S. states.
    - The chart data should represent state-level categories rather than a single state or a time series.
    - The insight should clearly communicate that the comparison is across U.S. states and mention at least one state by name.
    - The output should stay within the available data and not invent counties, countries, or unsupported metrics.
    """

    tool_output = await run_insights(query, TCL_US_STATES_STATE)
    verdict = await judge(query, rubric, tool_output)

    assert verdict.passed, verdict.comment
