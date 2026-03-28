"""
Eval tests: canopy cover threshold presentation in generate_insights output.

These tests verify that the LLM (via generate_insights) correctly follows the
updated dataset instructions around threshold disclosure:

  - TCL and Tree Cover insights must state the canopy threshold used
  - Forest Carbon Flux must mention the fixed 30% threshold
  - When the query carries explicit threshold context (e.g. country definition),
    the insight must reflect that threshold

Data side is deterministic (pre-baked fixtures). Only LLM calls are live.
"""

import copy

import pytest

from src.agent.state import Statistics
from src.agent.tools.datasets_config import DATASETS as _ALL_DATASETS
from tests.evals.fixture_data import GHG_FLUX_STATE, TCL_STATE, TREE_COVER_STATE

pytestmark = pytest.mark.asyncio(loop_scope="session")

_DS_BY_ID = {ds["dataset_id"]: ds for ds in _ALL_DATASETS}


def _dataset_fields(dataset_id: int, context_layer=None) -> dict:
    """Replicate the helper from fixture_data to build dataset state dicts."""
    ds = _DS_BY_ID[dataset_id]
    result = {
        "dataset_id": ds["dataset_id"],
        "dataset_name": ds["dataset_name"],
        "context_layer": context_layer,
        "tile_url": ds.get("tile_url", ""),
        "analytics_api_endpoint": ds.get("analytics_api_endpoint", ""),
        "description": ds.get("description", ""),
        "prompt_instructions": ds.get("prompt_instructions", ""),
        "methodology": ds.get("methodology", ""),
        "cautions": ds.get("cautions", ""),
        "function_usage_notes": ds.get("function_usage_notes", ""),
        "citation": ds.get("citation", ""),
    }
    for field in ("selection_hints", "code_instructions", "presentation_instructions"):
        val = ds.get(field)
        if val:
            result[field] = val
    return result


# ---------------------------------------------------------------------------
# Fixture: TCL state for India (represents a 10% threshold query context)
# The data itself is the same shape, but the query will carry the India context
# so the model must mention 10% not 30%.
# ---------------------------------------------------------------------------
_TCL_INDIA_STATE = {
    "dataset": _dataset_fields(4),
    "statistics": [
        Statistics(
            dataset_name="Tree cover loss",
            source_url="http://example.com/analytics/tcl-india-eval",
            start_date="2018-01-01",
            end_date="2023-12-31",
            aoi_names=["India"],
            data={
                "year": [2018, 2019, 2020, 2021, 2022, 2023],
                "area_ha": [165432, 183210, 172345, 158901, 189023, 176543],
                "emissions_MgCO2e": [73456, 81345, 76543, 70456, 83901, 78345],
                "aoi_id": ["IND"] * 6,
                "aoi_type": ["admin"] * 6,
            },
        )
    ],
}

# TCL by Driver state — Indonesia, driver breakdown
_TCL_DRIVER_THRESHOLD_STATE = {
    "dataset": _dataset_fields(8, context_layer="driver"),
    "statistics": [
        Statistics(
            dataset_name="Tree cover loss by dominant driver",
            source_url="http://example.com/analytics/tcl-driver-threshold-eval",
            start_date="2001-01-01",
            end_date="2024-12-31",
            aoi_names=["Indonesia"],
            data={
                "driver": [
                    "Permanent agriculture",
                    "Shifting cultivation",
                    "Logging",
                    "Wildfire",
                    "Hard commodities",
                ],
                "area_ha": [4523100, 3214500, 2876400, 1543200, 234500],
                "emissions_MgCO2e": [2012340, 1423560, 1278900, 687450, 104230],
                "aoi_id": ["IDN"] * 5,
                "aoi_type": ["admin"] * 5,
            },
        )
    ],
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_tcl_default_insight_mentions_threshold(run_insights, judge):
    """generate_insights must mention the 30% threshold for default TCL analysis."""
    query = "How much tree cover was lost in Pará, Brazil between 2015 and 2022?"
    result = await run_insights(query, TCL_STATE)
    verdict = await judge(
        query,
        """
        - The insight text or output must explicitly mention the canopy density threshold
          (30% is the default and expected value here).
        - The threshold mention may appear as "30%", "30 percent", or "30% canopy density".
        - It is acceptable if it appears in the chart title, caption, or summary text.
        - The output must NOT omit the threshold entirely.
        """,
        result,
    )
    assert verdict.passed, verdict.comment


async def test_tcl_chart_caption_includes_threshold(run_insights, judge):
    """TCL chart code should reference the canopy threshold in its title or caption.

    The agent selects 30% (GFW default) and passes it in the query to generate_insights.
    """
    query = (
        "Show annual tree cover loss in Pará, Brazil from 2015 to 2022. "
        "Using 30% canopy cover threshold (GFW default)."
    )
    result = await run_insights(query, TCL_STATE)
    verdict = await judge(
        query,
        """
        - The generated Python code or chart output must include a reference to the
          canopy density threshold, either in the chart title, subtitle, or a caption/annotation.
        - Acceptable: title contains "30%", subtitle says "canopy threshold: 30%",
          or a note in the printed output mentions the threshold.
        - The insight text alone is sufficient if it explicitly names the threshold.
        - The output must NOT be completely silent about the threshold.
        """,
        result,
    )
    assert verdict.passed, verdict.comment


async def test_tcl_india_query_context_threshold(run_insights, judge):
    """When the query explicitly states 10% threshold (India definition), the insight must reflect it.

    In real usage the agent selects 10% based on India's national forest definition
    and passes it to pull_data. Here we inject that context via the query so
    generate_insights receives it and must acknowledge it.
    """
    query = (
        "Show tree cover loss in India from 2018 to 2023. "
        "This analysis uses a 10% canopy cover threshold, "
        "consistent with India's national forest definition."
    )
    result = await run_insights(query, _TCL_INDIA_STATE)
    verdict = await judge(
        query,
        """
        - The insight or output must mention the 10% canopy density threshold.
        - It must NOT incorrectly state that 30% was used (30% is the global default
          but 10% was explicitly provided in the query for this analysis).
        - Acceptable forms: "10%", "10 percent canopy cover", "10% threshold".
        """,
        result,
    )
    assert verdict.passed, verdict.comment


async def test_ghg_flux_mentions_fixed_threshold(run_insights, judge):
    """Forest Carbon Flux insight must state the 30% threshold is fixed."""
    query = "What is the forest greenhouse gas net flux for Brazil?"
    result = await run_insights(query, GHG_FLUX_STATE)
    verdict = await judge(
        query,
        """
        - The insight must mention the 30% canopy density threshold.
        - The insight should indicate the threshold is fixed and cannot be changed
          (phrases like "fixed", "cannot be changed", or "fixed at 30%" are acceptable).
        - The threshold disclosure may appear in the insight text, chart caption, or
          the printed analysis output.
        """,
        result,
    )
    assert verdict.passed, verdict.comment


async def test_tree_cover_insight_mentions_threshold(run_insights, judge):
    """Tree Cover 2000 baseline insight must state the canopy threshold used.

    DRC uses 30% (UNFCCC REDD+ definition). The agent passes this in the query.
    """
    query = (
        "What was the tree cover extent in the Democratic Republic of Congo in 2000? "
        "Using 30% canopy cover threshold (DRC national definition per UNFCCC REDD+ Hub)."
    )
    result = await run_insights(query, TREE_COVER_STATE)
    verdict = await judge(
        query,
        """
        - The insight or output must mention the canopy density threshold (30% default).
        - Acceptable: "30%", "30 percent", "30% canopy cover", "30% threshold".
        - The threshold may appear in insight text, chart title, or printed output.
        - The output must NOT omit the threshold entirely.
        """,
        result,
    )
    assert verdict.passed, verdict.comment


async def test_tcl_by_driver_mentions_threshold(run_insights, judge):
    """TCL by driver breakdown must state the canopy threshold used.

    Indonesia uses 30% (GFW default). The agent passes this in the query.
    """
    query = (
        "What are the main drivers of tree cover loss in Indonesia from 2001 to 2024? "
        "This analysis uses the 30% canopy cover threshold (GFW default). "
        "State the threshold in the output."
    )
    result = await run_insights(query, _TCL_DRIVER_THRESHOLD_STATE)
    verdict = await judge(
        query,
        """
        - The insight or output must mention the canopy density threshold used.
        - 30% is the expected default value.
        - Acceptable forms: "30%", "30 percent canopy", "canopy threshold: 30%".
        - The threshold may appear in the insight, chart title, or printed output.
        - The output must NOT be completely silent about which threshold was applied.
        """,
        result,
    )
    assert verdict.passed, verdict.comment


async def test_tcl_does_not_use_term_deforestation(run_insights, judge):
    """
    Sanity check: TCL insight must use "tree cover loss" as the primary term.

    Included here to confirm that adding threshold instructions did not inadvertently
    break the existing "use tree cover loss not deforestation" rule.

    Note: mentioning "deforestation" to explain the distinction (e.g. "tree cover loss
    does not always equate to permanent deforestation") is acceptable and encouraged.
    """
    query = "How much forest was lost in Pará, Brazil between 2015 and 2022?"
    result = await run_insights(query, TCL_STATE)
    verdict = await judge(
        query,
        """
        - The primary term used to describe the phenomenon must be "tree cover loss",
          not "deforestation".
        - The output must NOT use "deforestation" as a synonym for or primary label of
          the data (e.g. "X ha of deforestation occurred" is NOT acceptable).
        - It IS acceptable — even good — to mention "deforestation" when explaining the
          distinction from tree cover loss (e.g. "tree cover loss does not always equate
          to permanent deforestation", "not all loss represents deforestation").
        - Check that the insight frames the data as tree cover loss, not as deforestation.
        """,
        result,
    )
    assert verdict.passed, verdict.comment
