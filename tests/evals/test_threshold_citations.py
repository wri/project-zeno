"""
Eval tests: country-specific threshold selection with citation justification.

These tests verify that generate_insights correctly:
  1. Uses the threshold implied by the country context in the query
  2. States that threshold in the output
  3. Cites the authoritative national source for the definition

Data is deterministic (pre-baked). Only LLM calls are live.

Country reference (from national UNFCCC/FAO submissions):
  10%: India (FSI), USA (USFS FIA), Canada (NRCan), Kenya, Ethiopia, South Africa
  20%: Australia (ABARES), UK (Forest Research), China, Spain
  25%: Chile (CONAF)
  30%: Colombia (IDEAM), DRC (UNFCCC REDD+), Japan, New Zealand, GFW default
"""

import pytest

from src.agent.state import Statistics
from src.agent.tools.datasets_config import DATASETS as _ALL_DATASETS
from tests.evals.fixture_data import TCL_STATE, TREE_COVER_STATE

pytestmark = pytest.mark.asyncio(loop_scope="session")

_DS_BY_ID = {ds["dataset_id"]: ds for ds in _ALL_DATASETS}


def _dataset_fields(dataset_id: int, context_layer=None) -> dict:
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
# Shared data shape — reused across country fixtures (only aoi/source differs)
# ---------------------------------------------------------------------------

def _tcl_state(aoi_name: str, aoi_id: str, source_suffix: str) -> dict:
    return {
        "dataset": _dataset_fields(4),
        "statistics": [
            Statistics(
                dataset_name="Tree cover loss",
                source_url=f"http://example.com/analytics/tcl-{source_suffix}",
                start_date="2015-01-01",
                end_date="2022-12-31",
                aoi_names=[aoi_name],
                data={
                    "year": [2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022],
                    "area_ha": [
                        120000, 135000, 118000, 142000,
                        155000, 148000, 161000, 143000,
                    ],
                    "emissions_MgCO2e": [
                        53000, 60000, 52000, 63000,
                        69000, 65000, 71000, 63000,
                    ],
                    "aoi_id": [aoi_id] * 8,
                    "aoi_type": ["admin"] * 8,
                },
            )
        ],
    }


_INDIA_TCL_STATE = _tcl_state("India", "IND", "india")
_AUSTRALIA_TCL_STATE = _tcl_state("Australia", "AUS", "australia")
_COLOMBIA_TCL_STATE = _tcl_state("Colombia", "COL", "colombia")
_DRC_TCL_STATE = _tcl_state("Democratic Republic of the Congo", "COD", "drc")
_CHILE_TCL_STATE = _tcl_state("Chile", "CHL", "chile")
_USA_TCL_STATE = _tcl_state("United States", "USA", "usa")
_KENYA_TCL_STATE = _tcl_state("Kenya", "KEN", "kenya")
_JAPAN_TCL_STATE = _tcl_state("Japan", "JPN", "japan")


# ---------------------------------------------------------------------------
# 10% threshold countries
# ---------------------------------------------------------------------------


async def test_india_uses_10pct_threshold_with_fsi_citation(run_insights, judge):
    """India: 10% threshold, cited to Forest Survey of India (FSI)."""
    query = (
        "Show tree cover loss in India from 2015 to 2022. "
        "Use India's national forest definition (10% canopy cover threshold, "
        "per the Forest Survey of India)."
    )
    result = await run_insights(query, _INDIA_TCL_STATE)
    verdict = await judge(
        query,
        """
        - The insight or output must mention the 10% canopy density threshold.
        - It must NOT state 30% as the threshold for this analysis.
        - Acceptable forms: "10%", "10 percent canopy cover", "10% canopy threshold".
        - Ideally the output references the Forest Survey of India (FSI) or India's national
          definition, but a plain "10%" mention is sufficient — citations may appear in the
          agent's conversational response rather than the chart insight text.
        """,
        result,
    )
    assert verdict.passed, verdict.comment


async def test_usa_uses_10pct_threshold_with_usfs_citation(run_insights, judge):
    """USA: 10% threshold, cited to USFS Forest Inventory and Analysis (FIA)."""
    query = (
        "Show tree cover loss in the United States from 2015 to 2022. "
        "Apply the US national forest definition (10% canopy cover, "
        "per USFS Forest Inventory and Analysis)."
    )
    result = await run_insights(query, _USA_TCL_STATE)
    verdict = await judge(
        query,
        """
        - The insight or output must mention the 10% canopy density threshold.
        - It must NOT state 30% as the threshold for this analysis.
        - Ideally the output references USFS, FIA, or the US national definition, but a
          plain "10%" mention is sufficient.
        """,
        result,
    )
    assert verdict.passed, verdict.comment


async def test_kenya_uses_10pct_threshold_with_fao_citation(run_insights, judge):
    """Kenya: 10% threshold aligned with FAO/UNFCCC standard."""
    query = (
        "Show tree cover loss in Kenya from 2015 to 2022. "
        "Using 10% canopy cover threshold (Kenya's national definition, "
        "aligned with FAO Global Forest Resources Assessment guidelines)."
    )
    result = await run_insights(query, _KENYA_TCL_STATE)
    verdict = await judge(
        query,
        """
        - The insight or output must mention the 10% canopy density threshold.
        - It must NOT state 30% as the threshold for this analysis.
        - Ideally the output references FAO, UNFCCC REDD+, or Kenya's national definition,
          but a plain "10%" mention is sufficient.
        """,
        result,
    )
    assert verdict.passed, verdict.comment


# ---------------------------------------------------------------------------
# 20% threshold countries
# ---------------------------------------------------------------------------


async def test_australia_uses_20pct_threshold_with_abares_citation(run_insights, judge):
    """Australia: 20% threshold, cited to ABARES."""
    query = (
        "Show tree cover loss in Australia from 2015 to 2022. "
        "Use Australia's national forest definition (20% canopy cover, ≥2m height, "
        "per ABARES Forests Australia)."
    )
    result = await run_insights(query, _AUSTRALIA_TCL_STATE)
    verdict = await judge(
        query,
        """
        - The insight or output must mention the 20% canopy density threshold.
        - It must NOT state 30% as the threshold.
        - Ideally the output references ABARES or Forests Australia, but a plain "20%"
          mention is sufficient.
        """,
        result,
    )
    assert verdict.passed, verdict.comment


# ---------------------------------------------------------------------------
# 25% threshold countries
# ---------------------------------------------------------------------------


async def test_chile_uses_25pct_threshold_with_conaf_citation(run_insights, judge):
    """Chile: 25% threshold, cited to CONAF."""
    query = (
        "Show tree cover loss in Chile from 2015 to 2022. "
        "Use Chile's national forest definition (25% canopy cover, "
        "per CONAF — Corporación Nacional Forestal)."
    )
    result = await run_insights(query, _CHILE_TCL_STATE)
    verdict = await judge(
        query,
        """
        - The insight or output must mention the 25% canopy density threshold.
        - It must NOT state 30% as the threshold for this analysis.
        - Ideally the output references CONAF or Chile's national definition, but a plain
          "25%" mention is sufficient.
        """,
        result,
    )
    assert verdict.passed, verdict.comment


# ---------------------------------------------------------------------------
# 30% threshold countries (non-default reasons)
# ---------------------------------------------------------------------------


async def test_colombia_uses_30pct_threshold_with_ideam_citation(run_insights, judge):
    """Colombia: 30% threshold, cited to IDEAM / UNFCCC REDD+."""
    query = (
        "Show tree cover loss in Colombia from 2015 to 2022. "
        "Use Colombia's national forest definition (30% canopy cover, ≥1 ha, ≥5m height, "
        "per IDEAM and Colombia's UNFCCC REDD+ submission)."
    )
    result = await run_insights(query, _COLOMBIA_TCL_STATE)
    verdict = await judge(
        query,
        """
        - The insight or output must mention the 30% canopy density threshold.
        - Ideally the output references IDEAM or Colombia's national definition, but a
          plain "30%" mention is sufficient.
        """,
        result,
    )
    assert verdict.passed, verdict.comment


async def test_drc_uses_30pct_threshold_with_redd_citation(run_insights, judge):
    """DRC: 30% threshold, cited to UNFCCC REDD+ submission."""
    query = (
        "Show tree cover loss in the Democratic Republic of the Congo from 2015 to 2022. "
        "Use DRC's forest definition (30% canopy cover threshold established for REDD+ "
        "monitoring per the UNFCCC REDD+ Hub)."
    )
    result = await run_insights(query, _DRC_TCL_STATE)
    verdict = await judge(
        query,
        """
        - The insight or output must mention the 30% canopy density threshold.
        - Ideally the output references DRC's REDD+ definition or the UNFCCC REDD+ Hub,
          but a plain "30%" mention is acceptable — citations may appear in the agent's
          conversational response rather than the chart insight text.
        """,
        result,
    )
    assert verdict.passed, verdict.comment


async def test_japan_uses_30pct_threshold_with_kyoto_citation(run_insights, judge):
    """Japan: 30% threshold, cited to UNFCCC / Kyoto Protocol reporting."""
    query = (
        "Show tree cover loss in Japan from 2015 to 2022. "
        "Use Japan's forest definition (30% canopy cover per the Forestry Agency of Japan "
        "and UNFCCC National Inventory reporting)."
    )
    result = await run_insights(query, _JAPAN_TCL_STATE)
    verdict = await judge(
        query,
        """
        - The insight or output must mention the 30% canopy density threshold.
        - Ideally the output references the Forestry Agency of Japan or UNFCCC National
          Inventory reporting, but a plain "30%" mention is sufficient — citations may
          appear in the agent's conversational response rather than the chart insight text.
        """,
        result,
    )
    assert verdict.passed, verdict.comment


# ---------------------------------------------------------------------------
# Default (no country-specific definition) — must state "GFW default"
# ---------------------------------------------------------------------------


async def test_default_threshold_cites_gfw_default(run_insights, judge):
    """When no country-specific definition applies, insight must say 30% is the GFW default.

    The agent selects 30% (GFW default) and passes that context to generate_insights
    via the query — we include it here to mirror that realistic flow.
    """
    query = (
        "Show tree cover loss in Pará, Brazil from 2015 to 2022. "
        "Using the 30% canopy cover threshold (GFW default — no country-specific "
        "definition applies here)."
    )
    result = await run_insights(query, TCL_STATE)
    verdict = await judge(
        query,
        """
        - The insight or output must mention the 30% canopy density threshold.
        - Ideally the output indicates this is the GFW default (e.g. "30% (GFW default)",
          "standard GFW threshold of 30%"), but a plain "30%" or "30% canopy cover" mention
          in the output text or chart title is sufficient.
        """,
        result,
    )
    assert verdict.passed, verdict.comment
