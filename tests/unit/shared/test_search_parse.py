"""Tests for the search-string parsing behind ``search_aois``."""

from src.shared.geocoding_helpers import SearchText, parse_search_text


def test_single_segment_has_no_context():
    assert parse_search_text("Paris") == SearchText("Paris", "")


def test_segments_after_the_leaf_become_context():
    assert parse_search_text("Bristol, England, United Kingdom") == SearchText(
        "Bristol", "England United Kingdom"
    )


def test_whitespace_and_empty_segments_are_dropped():
    assert parse_search_text("  Lisbon ,, Portugal  ") == SearchText(
        "Lisbon", "Portugal"
    )
    assert parse_search_text(",") == SearchText("", "")
    assert parse_search_text("") == SearchText("", "")


def test_nudge_decoration_is_stripped():
    """An ``aoi_choice`` option comes back verbatim as the next question."""
    assert parse_search_text(
        "Paris, Île-de-France, France - (district-county) [FRA]"
    ) == SearchText("Paris", "Île-de-France France")


def test_a_hyphen_inside_a_name_is_kept():
    assert parse_search_text("Resex Catua-Ipixuna") == SearchText(
        "Resex Catua-Ipixuna", ""
    )
