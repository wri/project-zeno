"""Deterministic candidate scoring for the `pick_aoi` geocoder (PZB-1272).

Retrieval and selection need different comparisons. `search_aois` ranks a
candidate list by match tier and prominence; the geocoder then has several
such lists, one per spelling it tried, and picks one row across all of them.
Selection therefore re-scores the retrieved rows here, accent-insensitively
and with the search's own rank as one term, instead of asking a model to
choose.

This module knows nothing about the tool it serves: it returns the winning
DataFrame row, and the caller turns that into an `AOIIndex`.
"""

import string
import unicodedata
from difflib import SequenceMatcher
from typing import Optional, Sequence

import pandas as pd

from src.shared.geocoding_helpers import HIERARCHY_SCORES
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

_SIMILARITY_WEIGHT = 0.5
_HIERARCHY_WEIGHT = 0.3
_EXACT_SEGMENT_BONUS = 0.2
_PREFIX_BONUS = 0.1
# The search's own rank (``similarity_score``, in [0, 1]) encodes what the
# string comparison here cannot see: whether the row matched an exact stored
# name, and whether the parent the user typed matched too. "Las Palmas,
# Spain" reads almost the same against the Canarian and the Panamanian Las
# Palmas, and only the rank knows which one is in Spain.
_DB_RANK_WEIGHT = 0.2

# Punctuation that can wrap a name segment. Stored names carry trailing
# commas ("NA, England, United Kingdom"), and an `aoi_choice` nudge option is
# resubmitted verbatim as the next question ("Paris, Ile-de-France, France -
# (district-county) [FRA]"), so a segment comparison that keeps punctuation
# would never match the same place spelled plainly.
_SEGMENT_PUNCTUATION = string.punctuation + string.whitespace

# The subtype preference lives with the search, which ranks by it in SQL;
# the scorer applies the same table so the two orderings agree.
_HIERARCHY_SCORES = HIERARCHY_SCORES


def _strip_accents(text_value: str) -> str:
    """Lowercase and remove diacritics: "Pará" -> "para"."""
    decomposed = unicodedata.normalize("NFD", text_value.lower())
    return "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    )


def leaf_key(leaf: str) -> str:
    """The form in which two leaf names are compared: accent-stripped,
    lowercased, outer punctuation removed."""
    return _strip_accents(leaf).strip(_SEGMENT_PUNCTUATION)


def _first_segment(name: str) -> str:
    """The leaf of a query term: its first comma-separated segment.

    The geocoder emits "Place, Parent" strings, so the first segment is the
    place's own name. A stored row carries its real leaf in the ``leaf``
    column; only a term, or a row without that column, is split here, because
    a stored leaf can itself contain a comma ("Krüger-, Rähden- und
    Möschensee").
    """
    return leaf_key(name.split(",")[0])


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


def _score_candidate(
    place_name: str, name: str, subtype: str, leaf: Optional[str] = None
) -> float:
    """Composite score for one AOI candidate against one search term.

    Weighted sum of accent-insensitive string similarity and an admin
    hierarchy preference, plus an exact-leaf-name bonus that falls back to a
    weaker prefix bonus. The leaf bonus is what separates "Pará" from
    "Paraná" for the term "Para". *leaf* is the row's stored leaf; without
    it the first segment of *name* stands in. ``best_candidate_row`` adds the
    search's own rank on top; this function scores the name alone.

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
        _candidate_leaf(name, leaf),
        _hierarchy_score(subtype),
        matcher,
    )


def _candidate_leaf(name: str, leaf: Optional[str]) -> str:
    """The comparison key of a row's leaf: the stored ``leaf`` when the row
    has one, else the first segment of its name."""
    if isinstance(leaf, str) and leaf:
        return leaf_key(leaf)
    return _first_segment(name)


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

    # A frame from a search carries the search's rank; one built by hand (a
    # test, a mocked query) may not, and then the rank term is zero.
    if "similarity_score" in candidate_aois.columns:
        db_ranks = candidate_aois["similarity_score"].fillna(0.0).tolist()
    else:
        db_ranks = [0.0] * len(candidate_aois)

    if "leaf" in candidate_aois.columns:
        leaves = candidate_aois["leaf"].tolist()
    else:
        leaves = [None] * len(candidate_aois)

    # Only the columns that scoring and the tie-break read, so no row this
    # function does not select is ever built as a dict.
    scoring_columns = zip(
        candidate_aois["name"],
        candidate_aois["subtype"],
        candidate_aois["source"],
        candidate_aois["src_id"],
        leaves,
        db_ranks,
    )
    for position, (name, subtype, source, src_id, leaf, db_rank) in enumerate(
        scoring_columns
    ):
        hierarchy = _hierarchy_score(subtype)
        candidate = _strip_accents(name)
        candidate_leaf = _candidate_leaf(name, leaf)
        matcher.set_seq2(candidate)
        score = max(
            _score_prepared(
                term, term_leaf, candidate, candidate_leaf, hierarchy, matcher
            )
            for term, term_leaf in term_forms
        ) + _DB_RANK_WEIGHT * float(db_rank)
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
