"""Deterministic candidate scoring for the `pick_aoi` geocoder (PZB-1272).

Retrieval and selection need different comparisons. `search_aois` ranks by
pg_trgm similarity over the whole stored name, which is accent-sensitive: for
the query "Para" it puts "Paraná" ABOVE "Pará", because the accent breaks
Pará's trigrams. Selection therefore re-scores the retrieved rows here,
accent-insensitively, instead of asking a model to repair the ranking.

Selection scores the LEAF, not the whole name (PZB-1392). Ingest composes
`aois.name` as "leaf, designation, ISO3" -- "Okapis, Réserve de Faune, COD" --
and a source-narrowed search returns rows that all share the designation and
country segments. Comparing whole names therefore ranks on the segments every
candidate has in common: "Sankuru National Reserve" scored 0.4674 against
"Samburu, National Reserve, KEN" and only 0.4442 against the Sankuru row,
because ", National Reserve, " is most of the string. The leaf is the only
segment that identifies the place, so it carries most of the weight, with a
smaller whole-name term left in to keep the parent hierarchy meaningful
("Lisboa, Portugal" over "Lisbon, Forest Preserve, USA").

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

# Weights, hand-tuned. Evidence they were set on, and what to rerun after
# changing them: the 22 recorded production frames
# (tests/unit/agent/tools/pick_aoi/test_designation_scoring.py), the 12
# recorded replay frames (tests/tools/test_pick_aoi.py under
# AOI_PICK_AOI_FIXTURES_MODE=replay) and the ladders pinned in test_scoring.py.
# The cohort result is flat at 20/22 across leaf 0.35-0.55 and whole
# 0.05-0.20, so these sit mid-plateau rather than on a tuned point. A zero
# whole-name weight is the one setting that breaks: it drops the parent
# hierarchy and loses the cases whose term carries a parent (ch-aoi-136,
# ch-aoi-145), and it moves a recorded replay frame.
_LEAF_WEIGHT = 0.60
_WHOLE_NAME_WEIGHT = 0.10
_HIERARCHY_WEIGHT = 0.3

# An exact name match wins outright. `_format_aoi_candidate` builds an
# `aoi_choice` option from a row's full stored name and documents that
# resubmitting it re-resolves to the row it names, and that guarantee cannot be
# left to a weighted sum: a child whose leaf repeats its parent's
# ("Senga, Senga, Butezi, Ruyigi, Burundi") ties its parent on every name term,
# and the hierarchy preference then hands the user the parent. The assertion
# below is what makes "wins outright" true rather than hoped for.
_EXACT_NAME_BONUS = 0.25

# There is no prefix bonus. Any bonus on top of the leaf comparison double
# counts, because an exact leaf already scores 1.0 there -- and a bonus gated on
# "not an exact leaf" is worse than none, because it then rewards every
# candidate EXCEPT the exact match: "Niger" scored 0.8500 against itself and
# 0.8583 against "Nigeria".

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

# The exact-name bonus only guarantees the round trip while it outweighs the
# widest hierarchy gap -- country over a named site, the two extremes of the
# map above. Pinned at import time rather than described in a comment, so that
# lowering the bonus or widening the hierarchy spread fails loudly here instead
# of silently returning a user's clicked option's parent.
_WIDEST_HIERARCHY_GAP = _HIERARCHY_WEIGHT * (
    max(_HIERARCHY_SCORES.values()) - min(_HIERARCHY_SCORES.values())
)
assert _EXACT_NAME_BONUS > _WIDEST_HIERARCHY_GAP, (
    f"_EXACT_NAME_BONUS ({_EXACT_NAME_BONUS}) must exceed the widest "
    f"hierarchy gap ({_WIDEST_HIERARCHY_GAP}), or an exact name match can "
    f"lose to a differently-named candidate of a broader subtype"
)


def _strip_accents(text_value: str) -> str:
    """Lowercase and remove diacritics: "Pará" -> "para"."""
    decomposed = unicodedata.normalize("NFD", text_value.lower())
    return "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    )


def _normalise_for_exact_match(text_value: str) -> str:
    """Accent-, case-, punctuation- and whitespace-insensitive name key.

    Both sides of the exact-name test go through this, so "Pará, Brazil"
    matches "Para,Brazil" and "Para, Brazil". Punctuation becomes a space
    rather than nothing, so "Kahuzi-Biega" cannot collapse into a different
    word.

    A decorated `aoi_choice` option ("... - (district-county) [FRA]") does NOT
    key equal to the stored name, and is not meant to: the geocoder extracts a
    place from that string before it reaches scoring, and what it extracts is
    the name.
    """
    stripped = _strip_accents(text_value)
    spaced = "".join(
        " " if char in _SEGMENT_PUNCTUATION else char for char in stripped
    )
    return " ".join(spaced.split())


def _first_segment(name: str) -> str:
    """The leaf name: first comma-separated segment, accent-stripped.

    Stored names are comma-joined most-specific-first ("Pará, Brazil";
    "Botum Sakor, ..., KHM") and the geocoder emits "Place, Parent" strings,
    so the first segment is the place's own name.
    """
    leaf = name.split(",")[0]
    return _strip_accents(leaf).strip(_SEGMENT_PUNCTUATION)


def _leaf_prefixes(term_leaf: str) -> list[str]:
    """The term leaf's word prefixes, longest first: what a stored leaf can be.

    A stored leaf is the place's own name; the extracted `place` term is that
    name followed by the designation the user used ("Sankuru National
    Reserve"), because English puts the designation last and GEOCODER_PROMPT
    translates into English. So the stored leaf, if this term names it at all,
    is a PREFIX of the term leaf.

    Prefixes rather than arbitrary interior spans, because the catalogue
    contains rows whose own leaf IS a designation word -- "Wildlife, Reserve,
    USA" and "Research, Natural Area, USA" are both real. An interior span
    would match those exactly and hand them the frame ("Okapi Wildlife
    Reserve" contains "Wildlife"), which is the defect this scoring replaces,
    only one level down.
    """
    words = term_leaf.split()
    return [" ".join(words[:end]) for end in range(len(words), 0, -1)] or [""]


def _prefix_matchers(
    term_leaf_prefixes: Sequence[str],
) -> list[SequenceMatcher]:
    """One matcher per prefix, each indexing its prefix as the SECOND sequence.

    `SequenceMatcher` is not symmetric -- its match recursion is greedy over
    the first sequence -- so which side goes where changes the score, and by
    enough to change a winner: "chiquibul" against "chiribiquete" scores
    0.4762 one way and 0.5714 the other. The prefix is seq2 because that is
    the side `SequenceMatcher` indexes, and the prefixes of a term set are
    fixed while the candidates vary, so they are indexed once for the whole
    frame rather than once per row.
    """
    matchers = []
    for prefix in term_leaf_prefixes:
        matcher = SequenceMatcher(None)
        matcher.set_seq2(prefix)
        matchers.append(matcher)
    return matchers


def _leaf_similarity(
    candidate_leaf: str, prefix_matchers: Sequence[SequenceMatcher]
) -> float:
    """How well the candidate's own name matches the name inside the term.

    Returns the best score over the term leaf's prefixes, which is what lets
    one term set serve both "Sankuru National Reserve" and the bare "Sankuru"
    without either spelling costing the other.
    """
    best = 0.0
    for matcher in prefix_matchers:
        matcher.set_seq1(candidate_leaf)
        ratio = matcher.ratio()
        if ratio > best:
            best = ratio
    return best


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
    term_exact_key: str,
    candidate: str,
    candidate_leaf: str,
    candidate_exact_key: str,
    hierarchy: float,
    prefix_matchers: Sequence[SequenceMatcher],
    whole_matcher: SequenceMatcher,
) -> float:
    """Score one prepared term against one prepared candidate.

    Every string here is already accent-stripped. *prefix_matchers* index the
    term's leaf prefixes and *whole_matcher* indexes the candidate's whole
    name, so between them every SequenceMatcher index is built once per frame
    or once per row, never once per comparison.

    There is no exact-leaf bonus: an exact leaf already scores 1.0 on the leaf
    term, so a bonus on top would double-count it. That double count is what
    let "Lisbon, Forest Preserve, USA" -- a site whose leaf is exactly
    "Lisbon" -- come within 0.0008 of outranking the Lisboa district.
    """
    whole_matcher.set_seq1(term)
    score = (
        _LEAF_WEIGHT * _leaf_similarity(candidate_leaf, prefix_matchers)
        + _WHOLE_NAME_WEIGHT * whole_matcher.ratio()
        + hierarchy
    )
    if term_exact_key == candidate_exact_key:
        score += _EXACT_NAME_BONUS
    return score


def _score_candidate(place_name: str, name: str, subtype: str) -> float:
    """Composite score for one AOI candidate against one search term.

    Weighted sum of an accent-insensitive LEAF comparison, a weaker
    whole-name comparison and an admin hierarchy preference, plus a prefix
    bonus. The leaf term is what separates "Pará" from "Paraná" for the term
    "Para", and what stops a shared designation deciding between two parks.

    Raises:
        ValueError: If ``subtype`` is not a known AOI subtype.
    """
    candidate = _strip_accents(name)
    candidate_leaf = _first_segment(name)
    term_leaf = _first_segment(place_name)
    whole_matcher = SequenceMatcher(None)
    whole_matcher.set_seq2(candidate)
    return _score_prepared(
        _strip_accents(place_name),
        _normalise_for_exact_match(place_name),
        candidate,
        candidate_leaf,
        _normalise_for_exact_match(name),
        _hierarchy_score(subtype),
        _prefix_matchers(_leaf_prefixes(term_leaf)),
        whole_matcher,
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

    # Each term is stripped, reduced to its leaf and indexed once, not once
    # per row.
    term_forms = [
        (
            _strip_accents(term),
            _normalise_for_exact_match(term),
            _prefix_matchers(_leaf_prefixes(_first_segment(term))),
        )
        for term in terms
    ]
    whole_matcher = SequenceMatcher(None)
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
        candidate_exact_key = _normalise_for_exact_match(name)
        whole_matcher.set_seq2(candidate)
        score = max(
            _score_prepared(
                term,
                term_exact_key,
                candidate,
                candidate_leaf,
                candidate_exact_key,
                hierarchy,
                prefix_matchers,
                whole_matcher,
            )
            for term, term_exact_key, prefix_matchers in term_forms
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
