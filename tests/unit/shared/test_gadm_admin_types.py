"""Unit tests for the GADM admin-type resolver - pure function, no DB needed."""

from src.shared.gadm_admin_types import (
    GADM_ADMIN_TERMS,
    GadmAdminTerm,
    resolve_gadm_admin_level,
)


def test_canonical_terms_cover_known_cases():
    """The curated vocabulary must include the terms the geocoder prompt
    examples rely on, or structured output can't extract them."""
    for term in [
        "Province",
        "State",
        "District",
        "Canton",
        "Emirate",
        "Constituent Country",
        "Municipality",
        "Department",
    ]:
        assert term in GADM_ADMIN_TERMS
        assert getattr(GadmAdminTerm, term.upper().replace(" ", "_")) == term


def test_province_is_country_specific_depth():
    """Spain's provinces (Sevilla, Almeria, ...) are one level deeper than
    Canada's - the whole point of resolving per country instead of globally."""
    assert resolve_gadm_admin_level("Province", "ESP") == 2
    assert resolve_gadm_admin_level("Province", "CAN") == 1


def test_shallowest_level_wins_on_ambiguity():
    """China's ENGTYPE "Municipality" appears at ADM1 (Beijing, Shanghai) and
    at deeper levels too; "municipalities of China" means the ADM1 sense."""
    assert resolve_gadm_admin_level("Municipality", "CHN") == 1


def test_single_country_terms_resolve():
    assert resolve_gadm_admin_level("Constituent Country", "GBR") == 1
    assert resolve_gadm_admin_level("Emirate", "ARE") == 1
    assert resolve_gadm_admin_level("Canton", "CHE") == 1


def test_typo_falls_back_to_closest_match():
    assert resolve_gadm_admin_level("Sate", "USA") == 1


def test_unresolvable_returns_none():
    assert resolve_gadm_admin_level("Province", "ZZZ") is None
    assert resolve_gadm_admin_level("Xyzzyplonk", "FRA") is None


def test_lowercase_input_matches():
    assert resolve_gadm_admin_level("province", "esp") == 2


def test_fuzzy_match_rejects_semantic_mismatches():
    """At a low cutoff, difflib matches English words that merely share
    letters with an unrelated GADM term (e.g. "City" -> "County",
    "Community" -> "Commune"). That's worse than doing nothing: a wrong
    fuzzy hit silently overrides the LLM's global default, where returning
    None would fall back to it. These must stay unresolved."""
    assert resolve_gadm_admin_level("City", "USA") is None
    assert resolve_gadm_admin_level("Community", "AGO") is None
    assert resolve_gadm_admin_level("County", "AGO") is None
    assert resolve_gadm_admin_level("Region", "ALA") is None
