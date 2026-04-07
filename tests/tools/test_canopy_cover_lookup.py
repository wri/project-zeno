"""
Unit tests for the canopy cover country lookup table and resolve_canopy_cover().

All tests are synchronous and require no network, database, or LLM calls.
"""

import pytest

from src.agent.tools.canopy_cover import (
    COUNTRY_THRESHOLDS,
    DEFAULT_CITATION,
    DEFAULT_THRESHOLD,
    resolve_canopy_cover,
)

# Override DB fixtures — these tests have no database dependency
@pytest.fixture(scope="function", autouse=True)
def test_db():
    pass


@pytest.fixture(scope="function", autouse=True)
def test_db_session():
    pass


@pytest.fixture(scope="function", autouse=True)
def test_db_pool():
    pass


# ---------------------------------------------------------------------------
# Helper AOI factories
# ---------------------------------------------------------------------------


def _country_aoi(iso3: str, name: str = "Country") -> dict:
    return {"source": "gadm", "subtype": "country", "src_id": iso3, "name": name}


def _state_aoi(src_id: str = "123", name: str = "State") -> dict:
    return {"source": "gadm", "subtype": "state", "src_id": src_id, "name": name}


def _wdpa_aoi(src_id: str = "456", name: str = "Protected Area") -> dict:
    return {"source": "wdpa", "subtype": "wdpa", "src_id": src_id, "name": name}


# ---------------------------------------------------------------------------
# resolve_canopy_cover: explicit override
# ---------------------------------------------------------------------------


class TestExplicitOverride:
    def test_explicit_beats_country_lookup(self):
        """An explicit threshold overrides the country mapping."""
        aois = [_country_aoi("IND")]
        threshold, citation = resolve_canopy_cover(aois, explicit=25)
        assert threshold == 25
        assert citation == "user-specified threshold"

    def test_explicit_beats_default(self):
        """An explicit threshold overrides the GFW default even with unknown country."""
        aois = [_country_aoi("ZZZ")]  # unknown ISO3
        threshold, citation = resolve_canopy_cover(aois, explicit=15)
        assert threshold == 15
        assert citation == "user-specified threshold"

    def test_explicit_zero_is_not_treated_as_falsy(self):
        """explicit=0 is technically falsy in Python; ensure it's handled as int check."""
        # 0 is not a valid GFW threshold, but the function should respect any non-None int.
        aois = [_country_aoi("IND")]
        threshold, citation = resolve_canopy_cover(aois, explicit=0)
        assert threshold == 0
        assert citation == "user-specified threshold"


# ---------------------------------------------------------------------------
# resolve_canopy_cover: country lookup
# ---------------------------------------------------------------------------


class TestCountryLookup:
    """Known countries must resolve to their national forest definition threshold."""

    @pytest.mark.parametrize(
        "iso3, expected_threshold",
        [
            # 10%
            ("IND", 10),
            ("USA", 10),
            ("CAN", 10),
            ("BRA", 10),
            ("MEX", 10),
            ("PER", 10),
            ("ARG", 10),
            ("ECU", 10),
            ("DEU", 10),
            ("FRA", 10),
            ("SWE", 10),
            ("FIN", 10),
            ("ITA", 10),
            ("NOR", 10),
            ("VNM", 10),
            ("PHL", 10),
            ("ZAF", 10),
            ("KEN", 10),
            ("ETH", 10),
            ("RUS", 10),
            # 20%
            ("AUS", 20),
            ("CHN", 20),
            ("GBR", 20),
            ("ESP", 20),
            # 25%
            ("CHL", 25),
            # 30%
            ("COL", 30),
            ("CRI", 30),
            ("COD", 30),
            ("COG", 30),
            ("JPN", 30),
            ("NZL", 30),
        ],
    )
    def test_known_country_threshold(self, iso3, expected_threshold):
        aois = [_country_aoi(iso3)]
        threshold, citation = resolve_canopy_cover(aois)
        assert threshold == expected_threshold, (
            f"{iso3}: expected {expected_threshold}%, got {threshold}%"
        )
        assert citation, f"{iso3}: citation must not be empty"

    def test_india_citation_references_fsi(self):
        """India's citation must point to the Forest Survey of India."""
        _, citation = resolve_canopy_cover([_country_aoi("IND")])
        assert "Forest Survey of India" in citation
        assert "fsi.nic.in" in citation

    def test_usa_citation_references_fia(self):
        _, citation = resolve_canopy_cover([_country_aoi("USA")])
        assert "FIA" in citation or "Forest Inventory" in citation

    def test_australia_citation_references_abares(self):
        _, citation = resolve_canopy_cover([_country_aoi("AUS")])
        assert "ABARES" in citation

    def test_chile_citation_references_conaf(self):
        _, citation = resolve_canopy_cover([_country_aoi("CHL")])
        assert "CONAF" in citation

    def test_colombia_citation_references_ideam(self):
        _, citation = resolve_canopy_cover([_country_aoi("COL")])
        assert "IDEAM" in citation


# ---------------------------------------------------------------------------
# resolve_canopy_cover: fallback to GFW default
# ---------------------------------------------------------------------------


class TestDefaultFallback:
    def test_unknown_country_returns_default(self):
        aois = [_country_aoi("ZZZ")]
        threshold, citation = resolve_canopy_cover(aois)
        assert threshold == DEFAULT_THRESHOLD
        assert citation == DEFAULT_CITATION

    def test_empty_aois_returns_default(self):
        threshold, citation = resolve_canopy_cover([])
        assert threshold == DEFAULT_THRESHOLD
        assert citation == DEFAULT_CITATION

    def test_sub_national_aoi_returns_default(self):
        """State-level AOIs must not match the country lookup."""
        aois = [_state_aoi("12345")]
        threshold, citation = resolve_canopy_cover(aois)
        assert threshold == DEFAULT_THRESHOLD

    def test_wdpa_aoi_returns_default(self):
        """Protected-area AOIs must not match the country lookup."""
        aois = [_wdpa_aoi("67890")]
        threshold, citation = resolve_canopy_cover(aois)
        assert threshold == DEFAULT_THRESHOLD

    def test_no_aoi_arg_returns_default(self):
        threshold, citation = resolve_canopy_cover([], explicit=None)
        assert threshold == DEFAULT_THRESHOLD
        assert citation == DEFAULT_CITATION


# ---------------------------------------------------------------------------
# resolve_canopy_cover: multi-AOI lists (subregion queries)
# ---------------------------------------------------------------------------


class TestMultiAOI:
    def test_first_country_aoi_wins(self):
        """When multiple country AOIs are present, the first one is used."""
        aois = [_country_aoi("IND"), _country_aoi("AUS")]
        threshold, _ = resolve_canopy_cover(aois)
        assert threshold == 10  # India's threshold

    def test_country_aoi_found_after_state_aois(self):
        """Country AOI later in list is still found (state AOIs are skipped)."""
        aois = [_state_aoi("1"), _state_aoi("2"), _country_aoi("AUS")]
        threshold, _ = resolve_canopy_cover(aois)
        assert threshold == 20  # Australia's threshold

    def test_mixed_sources_finds_gadm_country(self):
        aois = [_wdpa_aoi(), _country_aoi("CHL")]
        threshold, _ = resolve_canopy_cover(aois)
        assert threshold == 25


# ---------------------------------------------------------------------------
# COUNTRY_THRESHOLDS data integrity
# ---------------------------------------------------------------------------


class TestLookupTableIntegrity:
    def test_all_thresholds_are_valid_gfw_values(self):
        """Every threshold must be a value the GFW analytics API accepts."""
        valid = {10, 15, 20, 25, 30, 50, 75}
        for iso3, entry in COUNTRY_THRESHOLDS.items():
            assert entry["threshold"] in valid, (
                f"{iso3}: threshold {entry['threshold']} is not a valid GFW value"
            )

    def test_all_entries_have_citation(self):
        for iso3, entry in COUNTRY_THRESHOLDS.items():
            assert entry.get("citation"), f"{iso3}: citation must not be empty"

    def test_all_iso3_codes_are_three_letters(self):
        for iso3 in COUNTRY_THRESHOLDS:
            assert len(iso3) == 3 and iso3.isupper(), (
                f"'{iso3}' is not a valid ISO 3166-1 alpha-3 code"
            )

    def test_default_threshold_is_30(self):
        assert DEFAULT_THRESHOLD == 30

    def test_default_citation_references_gfw(self):
        assert "globalforestwatch.org" in DEFAULT_CITATION
