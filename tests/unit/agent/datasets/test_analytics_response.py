"""Nested analytics-result handling (Land GHG Inventory) in the analytics
handler's response processing.

RECONSTRUCTED after an accidental ``git clean`` — verify against intent before
relying on it. Nested results (per-section column dicts) must NOT go through the
flat ``aoi_id`` name-enrichment path, and the data-point count must come from
the first inner section's first list.
"""

from src.agent.datasets.handlers.analytics_handler import (
    _count_and_enrich,
    format_id,
)


def test_nested_result_counts_and_skips_name_enrichment():
    raw = {
        "vegetation": {
            "year": [2016, 2017, 2018],
            "net_flux_MgCO2e": [1, 2, 3],
        },
        "agriculture": {
            "category": ["cropland"],
            "gross_emissions_MgCO2e": [9],
        },
    }
    enriched, count = _count_and_enrich(
        raw, [{"src_id": "BRA.25", "name": "São Paulo, Brazil"}]
    )
    assert count == 3  # first section's first list length
    assert "name" not in enriched  # nested results skip aoi_id enrichment


def test_flat_result_enriches_names_and_counts():
    aois = [
        {"src_id": "BRA", "name": "Brazil"},
        {"src_id": "ARG", "name": "Argentina"},
    ]
    raw = {
        "aoi_id": [format_id("BRA"), format_id("ARG")],
        "value": [10, 20],
    }
    enriched, count = _count_and_enrich(raw, aois)
    assert count == 2
    assert enriched["name"] == ["Brazil", "Argentina"]
