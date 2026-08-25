"""Deterministic candidate scoring for the `pick_aoi` geocoder (PZB-1272).

Retrieval and selection need different comparisons. `search_aois` ranks by
pg_trgm similarity over the whole stored name, which is accent-sensitive: for
the query "Para" it puts "Paraná" ABOVE "Pará", because the accent breaks
Pará's trigrams. Selection therefore re-scores the retrieved rows here,
accent-insensitively, instead of asking a model to repair the ranking.

This module knows nothing about the tool it serves: it returns the winning
DataFrame row, and the caller turns that into an `AOIIndex`.
"""

import string
import unicodedata
from difflib import SequenceMatcher
from typing import Optional, Sequence

import pandas as pd

from src.shared.geocoding_helpers import SUBREGION_TO_SUBTYPE_MAPPING
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

_SIMILARITY_WEIGHT = 0.5
_HIERARCHY_WEIGHT = 0.3
_EXACT_SEGMENT_BONUS = 0.2
_PREFIX_BONUS = 0.1

# Punctuation that can wrap a name segment. Stored names carry trailing
# commas ("NA, England, United Kingdom"), and an `aoi_choice` nudge option is
# resubmitted verbatim as the next question ("Paris, Ile-de-France, France -
# (district-county) [FRA]"), so a segment comparison that keeps punctuation
# would never match the same place spelled plainly.
_SEGMENT_PUNCTUATION = string.punctuation + string.whitespace

# Preference by subtype: broader admin units beat narrower ones, and admin
# units beat named sites (KBA/WDPA/Landmark), so a bare "Lisbon" resolves to
# the Portuguese district rather than a small "Lisbon Forest Preserve". These
# ten values are everything `search_aois` can emit. The weights are tuning
# constants, hand-authored: they are not derived from any other ordering.
_HIERARCHY_SCORES: dict[str, float] = {
    "country": 1.0,
    "state-province": 0.9,
    "district-county": 0.7,
    "custom-area": 0.7,
    "municipality": 0.5,
    "locality": 0.35,
    "neighbourhood": 0.25,
    "key-biodiversity-area": 0.2,
    "protected-area": 0.2,
    "indigenous-and-community-land": 0.2,
}

# A subtype missing from the map raises on the query that returns it, so pin
# the coverage at import time: CI sees it, a user does not.
assert set(_HIERARCHY_SCORES) == set(SUBREGION_TO_SUBTYPE_MAPPING.values())


def _strip_accents(text_value: str) -> str:
    """Lowercase and remove diacritics: "Pará" -> "para"."""
    decomposed = unicodedata.normalize("NFD", text_value.lower())
    return "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    )


def _first_segment(name: str) -> str:
    """The leaf name: first comma-separated segment, accent-stripped.

    Stored names are comma-joined most-specific-first ("Pará, Brazil";
    "Botum Sakor, ..., KHM") and the geocoder emits "Place, Parent" strings,
    so the first segment is the place's own name.
    """
    leaf = name.split(",")[0]
    return _strip_accents(leaf).strip(_SEGMENT_PUNCTUATION)


def _hierarchy_score(subtype: str) -> float:
    """The weighted hierarchy term for one subtype.

    Raises:
        ValueError: If ``subtype`` is not a known AOI subtype.
    """
    if subtype not in _HIERARCHY_SCORES:
        raise ValueError(f"Unknown AOI subtype: {subtype!r}")
    return _HIERARCHY_WEIGHT * _HIERARCHY_SCORES[subtype]


def _score_prepared(
    term: str,
    term_leaf: str,
    candidate: str,
    candidate_leaf: str,
    hierarchy: float,
    matcher: SequenceMatcher,
) -> float:
    """Score one prepared term against one prepared candidate.

    Every string here is already accent-stripped, and *matcher* already holds
    the candidate as its second sequence: SequenceMatcher indexes that
    sequence once and reuses the index for every term, which is why the caller
    loops candidates on the outside and terms on the inside.
    """
    matcher.set_seq1(term)
    score = _SIMILARITY_WEIGHT * matcher.ratio() + hierarchy
    if term_leaf == candidate_leaf:
        score += _EXACT_SEGMENT_BONUS
    elif candidate.startswith(term):
        score += _PREFIX_BONUS
    return score


def _score_candidate(place_name: str, name: str, subtype: str) -> float:
    """Composite score for one AOI candidate against one search term.

    Weighted sum of accent-insensitive string similarity and an admin
    hierarchy preference, plus an exact-leaf-name bonus that falls back to a
    weaker prefix bonus. The leaf bonus is what separates "Pará" from
    "Paraná" for the term "Para".

    Raises:
        ValueError: If ``subtype`` is not a known AOI subtype.
    """
    candidate = _strip_accents(name)
    matcher = SequenceMatcher(None)
    matcher.set_seq2(candidate)
    return _score_prepared(
        _strip_accents(place_name),
        _first_segment(place_name),
        candidate,
        _first_segment(name),
        _hierarchy_score(subtype),
        matcher,
    )


def best_candidate_row(
    candidate_aois: pd.DataFrame, terms: Sequence[str]
) -> Optional[dict]:
    """Pick the best candidate deterministically, with no model call.

    Args:
        candidate_aois: Candidates from ``query_aoi_database`` or
            ``query_aoi_database_multiterm``.
        terms: The search terms this place was looked up under. A candidate
            keeps its BEST score across them, so a row that only a native
            spelling or an expanded acronym could find is not then penalised
            for mismatching the term the user typed.

    Returns:
        The highest scoring candidate as its DataFrame row, or None when there
        are none. None rather than an exception keeps the contract of the LLM
        selection this replaces: ``Geocoder.lookup`` reports the place as
        unmatched.

    Raises:
        ValueError: If ``terms`` is empty, or a candidate carries a subtype
            that is not in the hierarchy map.
    """
    if candidate_aois.empty:
        logger.debug("No candidate AOIs to select from")
        return None
    if not terms:
        raise ValueError("score_best_aoi needs at least one search term")

    # Each term is stripped and reduced to its leaf once, not once per row.
    term_forms = [
        (_strip_accents(term), _first_segment(term)) for term in terms
    ]
    matcher = SequenceMatcher(None)
    best_key: Optional[tuple] = None
    best_position = 0
    best_score = 0.0

    # Only the four columns that scoring and the tie-break read, so no row
    # this function does not select is ever built as a dict.
    scoring_columns = zip(
        candidate_aois["name"],
        candidate_aois["subtype"],
        candidate_aois["source"],
        candidate_aois["src_id"],
    )
    for position, (name, subtype, source, src_id) in enumerate(
        scoring_columns
    ):
        hierarchy = _hierarchy_score(subtype)
        candidate = _strip_accents(name)
        candidate_leaf = _first_segment(name)
        matcher.set_seq2(candidate)
        score = max(
            _score_prepared(
                term, term_leaf, candidate, candidate_leaf, hierarchy, matcher
            )
            for term, term_leaf in term_forms
        )
        # Compare on explicit secondary keys rather than the score alone, so
        # equal scores resolve identically whatever order the rows arrived in.
        key = (-score, name, source, str(src_id))
        if best_key is None or key < best_key:
            best_key = key
            best_position = position
            best_score = score

    # A one-row frame keeps every column's dtype, so this row is what
    # to_dict("records") would have produced for the whole frame.
    best_row: dict = candidate_aois.iloc[[best_position]].to_dict(
        orient="records"
    )[0]

    logger.debug(
        f"Selected AOI {best_row['src_id']} scoring {best_score:.3f} "
        f"from {len(candidate_aois)} candidate(s) for terms {list(terms)}"
    )
    return best_row
