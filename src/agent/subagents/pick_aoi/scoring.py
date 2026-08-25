"""Deterministic candidate scoring for the `pick_aoi` geocoder (PZB-1272).

Retrieval and selection need different comparisons. `search_aois` ranks by
pg_trgm similarity over the whole stored name, which is accent-sensitive: for
the query "Para" it puts "Paraná" ABOVE "Pará", because the accent breaks
Pará's trigrams. Selection therefore re-scores the retrieved rows here,
accent-insensitively, instead of asking a model to repair the ranking.

This module knows nothing about the tool it serves: it returns the winning
DataFrame row, and the caller turns that into an `AOIIndex`.
"""

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
_SEGMENT_PUNCTUATION = " \t.,;:!?'\"()[]-"

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


def _score_candidate(place_name: str, name: str, subtype: str) -> float:
    """Composite score for one AOI candidate against one search term.

    Weighted sum of accent-insensitive string similarity and an admin
    hierarchy preference, plus an exact-leaf-name bonus that falls back to a
    weaker prefix bonus. The leaf bonus is what separates "Pará" from
    "Paraná" for the term "Para".

    Raises:
        ValueError: If ``subtype`` is not a known AOI subtype.
    """
    if subtype not in _HIERARCHY_SCORES:
        raise ValueError(f"Unknown AOI subtype: {subtype!r}")

    term = _strip_accents(place_name)
    candidate = _strip_accents(name)

    similarity = SequenceMatcher(None, term, candidate).ratio()
    score = _SIMILARITY_WEIGHT * similarity
    score += _HIERARCHY_WEIGHT * _HIERARCHY_SCORES[subtype]

    if _first_segment(place_name) == _first_segment(name):
        score += _EXACT_SEGMENT_BONUS
    elif candidate.startswith(term):
        score += _PREFIX_BONUS

    return score


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

    scored = [
        (
            max(
                _score_candidate(term, row["name"], row["subtype"])
                for term in terms
            ),
            row,
        )
        for row in candidate_aois.to_dict(orient="records")
    ]
    # Sort with explicit secondary keys rather than taking a max, so equal
    # scores resolve identically whatever order the rows arrived in.
    scored.sort(
        key=lambda pair: (
            -pair[0],
            pair[1]["name"],
            pair[1]["source"],
            str(pair[1]["src_id"]),
        )
    )
    best_score, best_row = scored[0]

    logger.debug(
        f"Selected AOI {best_row['src_id']} scoring {best_score:.3f} "
        f"from {len(scored)} candidate(s) for terms {list(terms)}"
    )
    return best_row
