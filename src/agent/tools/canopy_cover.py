"""
Country-level canopy cover threshold lookup.

Maps ISO 3166-1 alpha-3 country codes to the national forest definition
threshold used by that country (or the FAO/UNFCCC standard where the country
has adopted it without publishing a distinct definition).

Threshold resolution priority (see resolve_canopy_cover):
  1. Explicit user override — user said "use 20% canopy cover"
  2. Country-specific lookup — first gadm country-level AOI in state
  3. GFW default (30%)
"""

from __future__ import annotations

from typing import TypedDict


class CountryThresholdEntry(TypedDict):
    threshold: int
    citation: str


DEFAULT_THRESHOLD = 30
DEFAULT_CITATION = (
    "[GFW default](https://www.globalforestwatch.org/); "
    "no country-specific definition applied"
)

# ISO 3166-1 alpha-3 → {"threshold": int, "citation": markdown_str}
COUNTRY_THRESHOLDS: dict[str, CountryThresholdEntry] = {
    # ── 10%: FAO/UNFCCC standard, broadly adopted ──────────────────────────
    "USA": {
        "threshold": 10,
        "citation": (
            "USA national forest definition per the "
            "[USFS Forest Inventory and Analysis (FIA)](https://www.fia.fs.usda.gov/)"
        ),
    },
    "CAN": {
        "threshold": 10,
        "citation": (
            "Canada's national forest definition per "
            "[Natural Resources Canada (NRCan)](https://natural-resources.canada.ca/"
            "our-natural-resources/forests/state-canadas-forests-report/"
            "how-does-canada-define-forest/17639)"
        ),
    },
    "BRA": {
        "threshold": 10,
        "citation": (
            "[FAO/UNFCCC standard forest definition](https://www.fao.org/forestry/fra/en/) "
            "(≥10% canopy cover, ≥0.5 ha, ≥5 m height)"
        ),
    },
    "MEX": {
        "threshold": 10,
        "citation": (
            "[FAO/UNFCCC standard forest definition](https://www.fao.org/forestry/fra/en/)"
        ),
    },
    "PER": {
        "threshold": 10,
        "citation": (
            "[FAO/UNFCCC standard forest definition](https://www.fao.org/forestry/fra/en/)"
        ),
    },
    "ARG": {
        "threshold": 10,
        "citation": (
            "[FAO/UNFCCC standard forest definition](https://www.fao.org/forestry/fra/en/)"
        ),
    },
    "ECU": {
        "threshold": 10,
        "citation": (
            "[FAO/UNFCCC standard forest definition](https://www.fao.org/forestry/fra/en/)"
        ),
    },
    "DEU": {
        "threshold": 10,
        "citation": (
            "[FAO/UNFCCC standard forest definition](https://www.fao.org/forestry/fra/en/)"
        ),
    },
    "FRA": {
        "threshold": 10,
        "citation": (
            "[FAO/UNFCCC standard forest definition](https://www.fao.org/forestry/fra/en/)"
        ),
    },
    "SWE": {
        "threshold": 10,
        "citation": (
            "[FAO/UNFCCC standard forest definition](https://www.fao.org/forestry/fra/en/)"
        ),
    },
    "FIN": {
        "threshold": 10,
        "citation": (
            "[FAO/UNFCCC standard forest definition](https://www.fao.org/forestry/fra/en/)"
        ),
    },
    "ITA": {
        "threshold": 10,
        "citation": (
            "[FAO/UNFCCC standard forest definition](https://www.fao.org/forestry/fra/en/)"
        ),
    },
    "NOR": {
        "threshold": 10,
        "citation": (
            "[FAO/UNFCCC standard forest definition](https://www.fao.org/forestry/fra/en/)"
        ),
    },
    "IND": {
        "threshold": 10,
        "citation": (
            "India's national forest definition per the "
            "[Forest Survey of India (FSI)](https://fsi.nic.in/)"
        ),
    },
    "VNM": {
        "threshold": 10,
        "citation": (
            "[FAO/UNFCCC standard forest definition](https://www.fao.org/forestry/fra/en/)"
        ),
    },
    "PHL": {
        "threshold": 10,
        "citation": (
            "[FAO/UNFCCC standard forest definition](https://www.fao.org/forestry/fra/en/)"
        ),
    },
    "ZAF": {
        "threshold": 10,
        "citation": (
            "[FAO/UNFCCC standard forest definition](https://www.fao.org/forestry/fra/en/)"
        ),
    },
    "KEN": {
        "threshold": 10,
        "citation": (
            "[FAO/UNFCCC standard forest definition](https://www.fao.org/forestry/fra/en/)"
        ),
    },
    "ETH": {
        "threshold": 10,
        "citation": (
            "[FAO/UNFCCC standard forest definition](https://www.fao.org/forestry/fra/en/)"
        ),
    },
    "RUS": {
        "threshold": 10,
        "citation": (
            "[FAO/UNFCCC standard forest definition](https://www.fao.org/forestry/fra/en/)"
        ),
    },
    # ── 20% ────────────────────────────────────────────────────────────────
    "AUS": {
        "threshold": 20,
        "citation": (
            "Australia's national forest definition per "
            "[ABARES](https://www.agriculture.gov.au/abares/forestsaustralia/"
            "forest-data-maps-and-tools/forest-definition)"
        ),
    },
    "CHN": {
        "threshold": 20,
        "citation": "China's national forest definition (≥20% canopy cover)",
    },
    "GBR": {
        "threshold": 20,
        "citation": (
            "UK national forest definition per "
            "[Forest Research](https://www.forestresearch.gov.uk/tools-and-resources/"
            "statistics/statistics-by-topic/woodland-statistics/)"
        ),
    },
    "ESP": {
        "threshold": 20,
        "citation": (
            "Spain's national forest definition per "
            "[FAO Global Forest Resources Assessment](https://www.fao.org/forestry/fra/en/)"
        ),
    },
    # ── 25% ────────────────────────────────────────────────────────────────
    "CHL": {
        "threshold": 25,
        "citation": (
            "Chile's national forest definition per [CONAF](https://www.conaf.cl/)"
        ),
    },
    # ── 30%: country-specific definitions that match GFW default ───────────
    "COL": {
        "threshold": 30,
        "citation": (
            "Colombia's national forest definition per "
            "[IDEAM](https://www.ideam.gov.co/) / UNFCCC REDD+ submission"
        ),
    },
    "CRI": {
        "threshold": 30,
        "citation": (
            "Costa Rica's national forest definition per "
            "[FONAFIFO](https://www.fonafifo.go.cr/)"
        ),
    },
    "COD": {
        "threshold": 30,
        "citation": "DRC forest definition per UNFCCC REDD+ submission",
    },
    "COG": {
        "threshold": 30,
        "citation": DEFAULT_CITATION,
    },
    "JPN": {
        "threshold": 30,
        "citation": DEFAULT_CITATION,
    },
    "NZL": {
        "threshold": 30,
        "citation": DEFAULT_CITATION,
    },
}


def resolve_canopy_cover(
    aois: list[dict],
    explicit: int | None = None,
) -> tuple[int, str]:
    """Resolve the canopy cover threshold and citation for a query.

    Priority:
      1. Explicit user override — if the user directly named a threshold, use it.
      2. Country-level lookup — ISO3 src_id from the first gadm country AOI in
         ``aois``. Sub-national or non-gadm AOIs are not matched (defaults to 30%).
      3. GFW default (30%).

    Args:
        aois: List of AOI dicts from ``state["aoi_selection"]["aois"]``.
        explicit: User-specified threshold (the ``canopy_cover`` parameter on
            the ``pull_data`` tool), or ``None`` when not provided.

    Returns:
        ``(threshold, citation_markdown)`` — threshold as an int, citation as a
        markdown string suitable for inclusion in the agent response.
    """
    if explicit is not None:
        return explicit, "user-specified threshold"

    for aoi in aois:
        if aoi.get("source") == "gadm" and aoi.get("subtype") == "country":
            iso3 = aoi.get("src_id", "")
            entry = COUNTRY_THRESHOLDS.get(iso3)
            if entry:
                return entry["threshold"], entry["citation"]

    return DEFAULT_THRESHOLD, DEFAULT_CITATION
