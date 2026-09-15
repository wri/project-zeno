"""Unit tests for the deterministic AOI scorer: pure functions, no DB, no LLM.

`score_best_aoi` is the tool-side wrapper that turns the winning row into an
AOIIndex; everything it scores with lives in `pick_aoi/scoring.py`.
"""

import pandas as pd
import pytest

from src.agent.subagents.pick_aoi.scoring import (
    _first_segment,
    _leaf_prefixes,
    _leaf_similarity,
    _prefix_matchers,
    _score_candidate,
    _strip_accents,
)
from src.agent.subagents.pick_aoi.tool import score_best_aoi
from src.shared.geocoding_helpers import WORLD_BBOX
from tests.unit.agent.tools.pick_aoi.conftest import _row


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
# above Pará. The same four rows and scores are mirrored in
# tests/agent/test_graph.py; `bbox` is left out because the recording predates
# that column.
_PARA_CANDIDATES = pd.DataFrame(
    [
        _row(
            "BRA.16_1",
            "Paraná, Brazil",
            subtype="state-province",
            score=0.7333333492279053,
            bbox=None,
        ),
        _row(
            "BRA.14_1",
            "Pará, Brazil",
            subtype="state-province",
            score=0.7142857313156128,
            bbox=None,
        ),
        _row(
            "BRA.15_1",
            "Paraíba, Brazil",
            subtype="state-province",
            score=0.6875,
            bbox=None,
        ),
        _row(
            "BRA.15.12_2",
            "Arara, Paraíba, Brazil",
            subtype="district-county",
            score=0.6315789222717285,
            bbox=None,
        ),
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


def test_the_designation_no_longer_decides_which_park_is_chosen():
    """The Botum Sakor case, on the candidate names production returns.

    This test used to pin the opposite: that the user's wording ALONE picked a
    foreign park, and only the canonical leaf in the term set rescued the
    intended row. That contrast was the PZB-1392 defect stated as an
    expectation -- the designation, shared by every candidate, outscored the
    leaf that identifies the place. Scoring the leaf removes it, so BOTH term
    sets now select Botum Sakor, and the canonical spelling is what it was
    always meant to be: extra recall, not a rescue.
    """
    candidates = pd.DataFrame(
        [
            _row(
                "478405",
                "Botum Sakor, ឧទ្យានជាតិ ដើម, KHM",
                "wdpa",
                "protected-area",
            ),
            _row("555", "Boma, National Park, SSD", "wdpa", "protected-area"),
            _row("556", "Bako, National Park, MYS", "wdpa", "protected-area"),
        ]
    )

    raw_only = score_best_aoi(candidates, ["Botum Sakor National Park"])
    with_canonical = score_best_aoi(
        candidates, ["Botum Sakor National Park", "Botum Sakor"]
    )

    assert raw_only is not None and raw_only.src_id == "478405"
    assert with_canonical is not None
    assert with_canonical.src_id == "478405"


@pytest.mark.parametrize(
    "terms,right,wrong",
    [
        (
            ["Sankuru National Reserve", "Sankuru"],
            ("354001", "Sankuru, Réserve Naturelle, COD"),
            ("2298", "Samburu, National Reserve, KEN"),
        ),
        (
            ["Yaguas National Park", "Yaguas"],
            ("555629239", "Yaguas, Parque Nacional, PER"),
            ("555625705", "Yanga, National Park, AUS"),
        ),
        (
            ["Okapi Wildlife Reserve", "Okapis"],
            ("37043", "Okapis, Réserve de Faune, COD"),
            ("1445", "Ajai, Wildlife Reserve, UGA"),
        ),
        (
            ["Ivindo National Park", "Ivindo"],
            ("303873", "Ivindo, Parc National, GAB"),
            ("X", "Ivanhoe, National Park, AUS"),
        ),
    ],
    ids=["sankuru", "yaguas", "okapi", "ivindo"],
)
def test_a_shared_designation_cannot_outrank_the_leaf_name(
    terms, right, wrong
):
    """PZB-1392, on the four pairs production actually confused.

    Every one of these lost on the shipped scorer, or (Ivindo) won by 0.005:
    the stored designation differs by language, so the English designation the
    user typed matched the WRONG country's row almost exactly.
    """
    candidates = pd.DataFrame(
        [
            _row(wrong[0], wrong[1], "wdpa", "protected-area"),
            _row(right[0], right[1], "wdpa", "protected-area"),
        ]
    )

    selected = score_best_aoi(candidates, terms)

    assert selected is not None
    assert selected.src_id == right[0]


def test_an_admin_unit_beats_a_same_named_site_by_more_than_a_rounding_error():
    """The Lisbon case, which the shipped scorer won by 0.000802.

    "Lisbon, Forest Preserve, USA" has "Lisbon" as its exact leaf while the
    Portuguese district is stored as "Lisboa", so the site wins the leaf
    comparison outright and only the hierarchy separates them. That margin is
    what the weights have to keep, and a hundredth of a point is the least
    that can be called a decision.
    """
    district = _score_candidate(
        "Lisbon", "Lisboa, Portugal", "district-county"
    )
    site = _score_candidate(
        "Lisbon", "Lisbon, Forest Preserve, USA", "protected-area"
    )

    assert district - site > 0.01


def test_ties_break_independently_of_candidate_order():
    tied = pd.DataFrame(
        [
            _row("B", "Springfield, Country B", subtype="state-province"),
            _row("A", "Springfield, Country A", subtype="state-province"),
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
    assert selected.bbox == WORLD_BBOX


# ---------------------------------------------------------------------------
# Leaf-name comparison (PZB-1392). The stored `name` carries the designation
# and the country as its 2nd and 3rd segments, so the leaf is the only segment
# that identifies the place.
# ---------------------------------------------------------------------------


def test_leaf_prefixes_are_longest_first_and_never_interior_spans():
    assert _leaf_prefixes("okapi wildlife reserve") == [
        "okapi wildlife reserve",
        "okapi wildlife",
        "okapi",
    ]
    assert _leaf_prefixes("sankuru") == ["sankuru"]
    assert _leaf_prefixes("") == [""]


def _leaf_sim(term, candidate_name):
    """`_leaf_similarity` with the plumbing a caller does."""
    return _leaf_similarity(
        _first_segment(candidate_name),
        _prefix_matchers(_leaf_prefixes(_first_segment(term))),
    )


def test_leaf_similarity_finds_the_place_name_inside_a_designation_phrase():
    """The PZB-1392 core: the leaf, not the designation, does the matching."""
    right = _leaf_sim(
        "Sankuru National Reserve", "Sankuru, Réserve Naturelle, COD"
    )
    wrong = _leaf_sim(
        "Sankuru National Reserve", "Samburu, National Reserve, KEN"
    )

    assert right == 1.0
    assert right > wrong


def test_leaf_similarity_ignores_a_designation_word_that_is_itself_a_leaf():
    """ "Wildlife, Reserve, USA" and "Research, Natural Area, USA" are real rows.

    An interior-span comparison would score them 1.0 against any term
    containing that word, which is how a designation would keep deciding.
    """
    designation_leaf = _leaf_sim(
        "Okapi Wildlife Reserve", "Wildlife, Reserve, USA"
    )
    real_leaf = _leaf_sim(
        "Okapi Wildlife Reserve", "Okapis, Réserve de Faune, COD"
    )

    assert real_leaf > designation_leaf


def test_leaf_similarity_ignores_the_terms_parent_segment():
    """ "Para, Brazil" must not match the country row on its parent segment."""
    state = _leaf_sim("Para, Brazil", "Pará, Brazil")
    country = _leaf_sim("Para, Brazil", "Brazil")

    assert state == 1.0
    assert state > country
