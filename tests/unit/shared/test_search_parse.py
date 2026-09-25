"""Tests for the search-string parsing behind ``search_aois``."""

from src.shared.aoi_search import (
    SearchText,
    _corrected_query,
    _LeafToken,
    _prefix_tsquery,
    _reduced_queries,
    parse_search_text,
)


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


def test_a_hyphen_inside_a_name_is_kept():
    assert parse_search_text("Resex Catua-Ipixuna") == SearchText(
        "Resex Catua-Ipixuna", ""
    )


def test_prefix_tsquery_marks_the_last_lexeme_as_a_prefix():
    assert _prefix_tsquery(["bangalore", "ur"]) == "'bangalore' & 'ur':*"
    assert _prefix_tsquery(["d'ivoire"]) == "'d''ivoire':*"
    assert _prefix_tsquery([]) is None
    assert _prefix_tsquery(None) is None


def _token(lexeme, ndoc=5, nearest=None):
    return _LeafToken(
        lexeme, ndoc, (lexeme,) if nearest is None else tuple(nearest)
    )


def test_corrected_query_ors_the_neighbours_of_each_word():
    tokens = [_token("sao"), _token("paolo", 12, ["paulo", "paola", "paolo"])]
    assert (
        _corrected_query(tokens) == "('sao') & ('paulo' | 'paola' | 'paolo')"
    )
    # A word too short to correct passes through as typed.
    assert _corrected_query([_token("np", 0, []), _token("serengeti")]) is None
    # No neighbour but itself: the query would repeat the one that missed.
    assert (
        _corrected_query([_token("serengeti"), _token("np", 70, [])]) is None
    )
    # A correctable word with nothing near it makes the whole query empty.
    assert (
        _corrected_query([_token("czech", 0, []), _token("republic")]) is None
    )


def test_reduced_queries_drop_the_last_then_the_first_word():
    assert _reduced_queries(
        [
            _token("ho", 516),
            _token("chi", 474),
            _token("minh", 664),
            _token("city", 7977),
        ]
    ) == ["'ho' & 'chi' & 'minh'", "'chi' & 'minh' & 'city'"]
    assert _reduced_queries([_token("paris")]) == []


def test_reduced_queries_keep_only_words_that_can_name_a_place():
    # "np" alone is too short to be a name; "serengeti" is one.
    assert _reduced_queries([_token("serengeti", 33), _token("np", 70)]) == [
        "'serengeti'"
    ]
    # Two words together are selective even when each is everywhere.
    assert _reduced_queries(
        [_token("mount", 1453), _token("kenya", 2205), _token("np", 70)]
    ) == ["'mount' & 'kenya'", "'kenya' & 'np'"]
    # "czech" is absent and "republic" is everywhere: neither half is a place.
    assert (
        _reduced_queries([_token("czech", 0, []), _token("republic", 1339)])
        == []
    )
    # "sao" is everywhere; "paolo" is rare, so only the second half is tried.
    assert _reduced_queries([_token("sao", 1665), _token("paolo", 12)]) == [
        "'paolo'"
    ]
