"""Unit tests for the deterministic AOI scorer: pure functions, no DB, no LLM.

`score_best_aoi` is the tool-side wrapper that turns the winning row into an
AOIIndex; everything it scores with lives in `pick_aoi/scoring.py`.
"""

import pandas as pd
import pytest

from src.agent.subagents.pick_aoi.scoring import (
    _first_segment,
    _score_candidate,
    _strip_accents,
)
from src.agent.subagents.pick_aoi.tool import score_best_aoi


def test_accents_are_ignored_when_names_are_compared():
    assert _strip_accents("Pará") == "para"
    assert _strip_accents("São Paulo") == "sao paulo"
    assert _strip_accents("Côte d'Ivoire") == "cote d'ivoire"


def test_leaf_name_is_the_first_segment_of_a_comma_joined_name():
    assert _first_segment("Pará, Brazil") == "para"
    assert _first_segment("Arara, Paraíba, Brazil") == "arara"
    assert _first_segment("Botum Sakor, ឧទ្យានជាតិ ដើម, KHM") == "botum sakor"


def test_leaf_name_ignores_surrounding_punctuation():
    """A trailing comma or bracketed suffix must not defeat leaf matching.

    GADM stores "NA, England, United Kingdom", and an aoi_choice nudge option
    is resubmitted verbatim as the next question, so both spellings of the
    same leaf have to compare equal.
    """
    assert _first_segment("England,") == _first_segment("England")
    assert _first_segment("(Paris)") == "paris"
    assert (
        _first_segment("Paris, Ile-de-France, France - (district) [FRA]")
        == "paris"
    )


def test_scoring_rejects_an_unknown_subtype():
    with pytest.raises(ValueError, match="Unknown AOI subtype"):
        _score_candidate("Brazil", "Brazil", "planet")


def test_accent_insensitive_scoring_prefers_para_over_parana():
    """The production bug, pinned on the recorded candidate names.

    In tests/fixtures/aoi_pick_aoi_v1.json the DB ranks Paraná (0.733) above
    Pará (0.714) for the term "Para, Brazil"; the scorer must invert that.
    """
    para = _score_candidate("Para, Brazil", "Pará, Brazil", "state-province")
    parana = _score_candidate(
        "Para, Brazil", "Paraná, Brazil", "state-province"
    )
    paraiba = _score_candidate(
        "Para, Brazil", "Paraíba, Brazil", "state-province"
    )

    assert para > parana
    assert para > paraiba


def test_exact_leaf_match_outscores_a_prefix_match():
    exact = _score_candidate("Ivory Coast", "Ivory Coast", "country")
    prefix = _score_candidate("Ivory Coast", "Ivory Coast Preserve", "country")
    unrelated = _score_candidate("Ivory Coast", "West Coast", "country")

    assert exact > prefix > unrelated


def test_hierarchy_separates_identically_named_places():
    country = _score_candidate("Luxembourg", "Luxembourg", "country")
    state = _score_candidate("Luxembourg", "Luxembourg", "state-province")
    site = _score_candidate(
        "Luxembourg", "Luxembourg", "key-biodiversity-area"
    )

    assert country > state > site


# Verbatim rows from tests/fixtures/aoi_pick_aoi_v1.json for "Para, Brazil",
# in the order the DB returned them — Paraná first, because pg_trgm ranks it
# above Pará.
_PARA_CANDIDATES = pd.DataFrame(
    [
        {
            "src_id": "BRA.16_1",
            "name": "Paraná, Brazil",
            "subtype": "state-province",
            "source": "gadm",
            "similarity_score": 0.7333333492279053,
        },
        {
            "src_id": "BRA.14_1",
            "name": "Pará, Brazil",
            "subtype": "state-province",
            "source": "gadm",
            "similarity_score": 0.7142857313156128,
        },
        {
            "src_id": "BRA.15_1",
            "name": "Paraíba, Brazil",
            "subtype": "state-province",
            "source": "gadm",
            "similarity_score": 0.6875,
        },
        {
            "src_id": "BRA.15.12_2",
            "name": "Arara, Paraíba, Brazil",
            "subtype": "district-county",
            "source": "gadm",
            "similarity_score": 0.6315789222717304,
        },
    ]
)


def test_no_candidates_selects_nothing():
    """Empty frame returns None, not an exception: lookup reports the place
    as unmatched, exactly as it did under LLM selection."""
    assert score_best_aoi(pd.DataFrame(), ["Anywhere"]) is None


def test_selection_without_a_search_term_is_a_programming_error():
    with pytest.raises(ValueError, match="at least one search term"):
        score_best_aoi(_PARA_CANDIDATES, [])


def test_single_candidate_is_selected():
    selected = score_best_aoi(_PARA_CANDIDATES.head(1), ["Para, Brazil"])

    assert selected is not None
    assert selected.src_id == "BRA.16_1"


def test_selection_overrides_the_accent_sensitive_db_ranking():
    """The production regression: the DB puts Paraná on top, the scorer
    must still select Pará for the term "Para, Brazil"."""
    selected = score_best_aoi(_PARA_CANDIDATES, ["Para, Brazil"])

    assert selected is not None
    assert selected.src_id == "BRA.14_1"
    assert selected.name == "Pará, Brazil"


def test_each_candidate_scores_against_its_best_term():
    """The Botum Sakor case, on the candidate names production returns.

    Scored against the user's wording alone, the designation ("National
    Park") dominates and a foreign park wins. The canonical leaf name in the
    term set is what makes the intended row win.
    """
    candidates = pd.DataFrame(
        [
            {
                "src_id": "478405",
                "name": "Botum Sakor, ឧទ្យានជាតិ ដើម, KHM",
                "subtype": "protected-area",
                "source": "wdpa",
            },
            {
                "src_id": "555",
                "name": "Boma, National Park, SSD",
                "subtype": "protected-area",
                "source": "wdpa",
            },
            {
                "src_id": "556",
                "name": "Bako, National Park, MYS",
                "subtype": "protected-area",
                "source": "wdpa",
            },
        ]
    )

    raw_only = score_best_aoi(candidates, ["Botum Sakor National Park"])
    with_canonical = score_best_aoi(
        candidates, ["Botum Sakor National Park", "Botum Sakor"]
    )

    assert raw_only is not None and raw_only.src_id != "478405"
    assert with_canonical is not None
    assert with_canonical.src_id == "478405"


def test_ties_break_independently_of_candidate_order():
    tied = pd.DataFrame(
        [
            {
                "src_id": "B",
                "name": "Springfield, Country B",
                "subtype": "state-province",
                "source": "gadm",
            },
            {
                "src_id": "A",
                "name": "Springfield, Country A",
                "subtype": "state-province",
                "source": "gadm",
            },
        ]
    )

    forwards = score_best_aoi(tied, ["Springfield"])
    backwards = score_best_aoi(tied.iloc[::-1], ["Springfield"])

    assert forwards is not None and backwards is not None
    assert forwards.src_id == backwards.src_id == "A"


def test_selected_aoi_keeps_the_state_shape_of_an_aoi_selection_entry():
    """No scoring field may leak through AOIIndex(extra="allow")."""
    selected = score_best_aoi(_PARA_CANDIDATES, ["Para, Brazil"])

    assert selected is not None
    assert set(selected.model_dump()) == {
        "source",
        "src_id",
        "name",
        "subtype",
        "bbox",
        "similarity_score",
    }
    # bbox is absent from the recorded fixture columns, so the model default
    # (the world bbox) must fill it.
    assert selected.bbox == [-180.0, -90.0, 180.0, 90.0]
