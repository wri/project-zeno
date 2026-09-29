"""AOI name search: the read side shared by ``GET /api/aois`` and the
``pick_aoi`` geocoder.

``search_aois`` is the entry point. docs/aoi-full-text-search.md describes
the tiers, the miss path and the autocomplete mode; the write side that
fills the columns this module reads is in :mod:`src.shared.aoi_search_sql`
(the fragments) and ``build-aois`` (the build).
"""

from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional

import pandas as pd
from sqlalchemy import text

from src.shared.aoi_search_sql import TS_CONFIG, hierarchy_prior_sql, norm_sql
from src.shared.database import get_connection_from_pool
from src.shared.geocoding_helpers import (
    VALID_AOI_SOURCES,
    normalize_aoi_source,
)


@dataclass(frozen=True)
class SearchText:
    """A search string split the way the stored names are: leaf, then context.

    ``leaf`` is the place's own name and ``context`` the parents that follow
    it, joined by spaces; ``context`` is empty when the string has one
    segment. Both are raw text: the SQL normalizes them with the same
    functions that normalized the stored names.
    """

    leaf: str
    context: str


def parse_search_text(name: str) -> SearchText:
    """Split *name* on commas into a leaf and its context.

    The geocoder sends "Place, Parent" strings, and the stored names are
    comma-joined most-specific-first, so the first segment is the place and
    the rest is where it is. A segment of only whitespace is dropped.
    """
    segments = [s.strip() for s in name.split(",")]
    segments = [s for s in segments if s]
    if not segments:
        return SearchText("", "")
    return SearchText(segments[0], " ".join(segments[1:]))


# The order within a tier: a context hit first (the query named the parent
# and this row has it), then the hierarchy prior, then a match on the leaf
# over one on a variant ("Lisbon" is Lisboa before a US preserve called
# Lisbon, because the prior outranks the leaf key),
# the larger area, and a stable name/id tie-break. Booleans are compared IS
# TRUE so a NULL leaf or context sorts as false rather than first. Every
# candidate arm sorts by the same keys, which is what makes a per-arm LIMIT
# exact: a row in the final top-N with best tier t sits within the top-N of
# arm t, because every row above it in that arm also ranks above it in the
# result.
_CONTEXT_HIT = "(q.cq IS NOT NULL AND a.search_tsv @@ q.cq) IS TRUE"
_EXACT_LEAF = "(a.leaf_norm = :leaf_norm) IS TRUE"
_TIE_BREAK = [
    "a.area_km2 DESC NULLS LAST",
    "a.name",
    "a.source",
    "a.source_id",
]


def _order_within_tier(prior: str, with_context: bool) -> str:
    """The ORDER BY keys of the search arms and of the final result.

    Without a typed context the context key is left out rather than made a
    constant, which keeps the exact and prefix arms free of any column
    outside the covering index (see idx_aois_leaf_norm).
    """
    keys = [f"{_CONTEXT_HIT} DESC"] if with_context else []
    keys += [f"{prior} DESC", f"{_EXACT_LEAF} DESC", *_TIE_BREAK]
    return ", ".join(keys)


# The normalized leaf and its LIKE prefix are bound as constants, computed by
# this statement first: a LIKE whose pattern is a column cannot become an
# index range, and the same normalization must apply to the query as to the
# stored names. The prefix escapes LIKE's wildcards.
_NORMALIZE_LEAF_SQL = f"""
    SELECT n,
           replace(replace(replace(n, '\\', '\\\\'), '%', '\\%'), '_', '\\_')
             || '%',
           (SELECT array_agg(lexeme ORDER BY positions[1])
            FROM unnest(to_tsvector('{TS_CONFIG}', :leaf))
            WHERE lexeme NOT LIKE '%-%'),
           (SELECT array_agg(lexeme ORDER BY positions[1])
            FROM unnest(to_tsvector('{TS_CONFIG}', :context))
            WHERE lexeme NOT LIKE '%-%')
    FROM (SELECT {norm_sql(":leaf")} AS n) s
"""
# The parser emits a hyphenated word twice: as the compound ("ile-de-france")
# and as its parts. Only the parts are used to build a query: quoting the
# compound in to_tsquery re-parses it into a phrase that never matches, and
# the parts alone match the same rows.

SearchMode = Literal["search", "autocomplete"]

# Autocomplete answers a keystroke, so it needs a couple of characters to
# have anything to complete, and it pages nothing: the next keystroke
# replaces the list.
AUTOCOMPLETE_MIN_CHARS = 2

# Caps on what one search may cost. A place name is never this long; the
# miss path runs one trigram lookup per distinct word, so both the length and
# the word count bound the work a request can demand. Paging past ten
# thousand rows is not a use case, and a huge offset would otherwise sort the
# whole table on disk.
MAX_SEARCH_NAME_CHARS = 200
MAX_SEARCH_OFFSET = 10_000
_MAX_MISS_LEXEMES = 6


class SearchRequestError(ValueError):
    """The caller's input cannot be searched as given (a 422 at the API)."""


def _custom_scope_sql(requested: set[str]) -> str:
    """Owner-scope custom areas through ``user_aois``, the permission model.

    ``aois.created_by`` records provenance and is not consulted. The clause
    is omitted when the caller does not ask for custom areas, because the
    source filter already excludes them.
    """
    if "custom" not in requested:
        return ""
    return """
        AND (a.source <> 'custom' OR EXISTS (
            SELECT 1 FROM user_aois ua
            WHERE ua.aoi_id = a.id
              AND ua.user_id = :user_id
              AND ua.relationship = 'owner'
        ))
    """


def _live_filters(requested: set[str]) -> str:
    """The WHERE clause every arm shares: live rows, in the asked sources."""
    return (
        "NOT a.is_disputed AND NOT a.is_deprecated "
        "AND a.source = ANY(:sources)" + _custom_scope_sql(requested)
    )


def _arm(
    tier: int, match: str, *, filters: str, order: str, join: str = ""
) -> str:
    """One candidate arm: the rows *match* selects, ranked and cut at k."""
    return (
        f"(SELECT a.id, {tier} AS tier FROM aois a {join}, q "
        f"WHERE {match} AND {filters} ORDER BY {order} LIMIT :k)"
    )


# The match tiers. A row keeps the best tier any arm gave it.
EXACT_TIER = 2  # the leaf, or a stored name variant, equals the query
PARTIAL_TIER = 1  # the query's tokens are in the name, or it is a prefix

# The rank a search returns as ``similarity_score``. It is a summary of the
# sort keys for callers that need one number (the API's ``score``, the
# geocoder's multi-term merge), not the sort key itself: the ORDER BY also
# breaks ties on an exact leaf and on area, which the score leaves out, so
# two rows with equal scores can come back in either order. The weights sum
# to 1 so the score stays in [0, 1], and keep the precedence of the sort:
# tier, then a context hit, then the prior.
_SCORE_TIER_WEIGHT = 0.55
_SCORE_CONTEXT_WEIGHT = 0.2
_SCORE_PRIOR_WEIGHT = 0.25
# Autocomplete has no context term: a typed parent filters, it does not rank.
_AUTOCOMPLETE_TIER_WEIGHT = 0.5
_AUTOCOMPLETE_PRIOR_WEIGHT = 0.5

# The columns every result carries, in the order callers and the recorded
# replay fixtures know them (a score and the search-only columns follow).
_RESULT_COLUMNS = """
            a.source_id AS src_id,
            a.name,
            a.subtype,
            a.source,
            COALESCE(
                a.bbox, ARRAY[-180, -90, 180, 90]::double precision[]
            ) AS bbox"""


def _tiered_statement(
    *,
    queries: str,
    arms: list[str],
    score: str,
    corrected: str,
    extra_columns: str,
    order: str,
    paging: str,
) -> str:
    """The shape search and autocomplete share.

    ``q`` holds the tsqueries, built once and inlined into each arm (NOT
    MATERIALIZED, so the planner sees them and uses the GIN indexes); each
    arm is a ranked, cut candidate list; a row keeps its best tier; the
    final ORDER BY repeats the arms' keys, which is what makes the per-arm
    cut exact.
    """
    return f"""
        WITH q AS NOT MATERIALIZED (
            SELECT {queries}
        ),
        cand AS ({" UNION ALL ".join(arms)}),
        best AS (SELECT id, max(tier) AS tier FROM cand GROUP BY id)
        SELECT {_RESULT_COLUMNS},
            {score} AS similarity_score,
            b.tier,
            a.leaf,
            {corrected} AS corrected{extra_columns}
        FROM best b
        JOIN aois a ON a.id = b.id, q
        ORDER BY b.tier DESC, {order}
        {paging}
    """


# The three shapes of the search statement. "typed" runs every arm as the
# user wrote the query; the others are the miss path and run the token arm
# only, since an exact or prefix match would already have been found.
# "fallback" reads the full vector for words spread over name and context
# ("Bristol England"); "retry" reads the name vector with a query prepared
# in Python (a corrected spelling, or a word dropped).
_SearchStage = Literal["typed", "fallback", "retry"]


def _search_sql(
    requested: set[str], *, stage: _SearchStage, with_context: bool
) -> str:
    """The tiered search statement. See docs/aoi-full-text-search.md.

    Tier 2 is an exact match on the leaf or on any stored name variant; tier
    1 is a partial match: the leaf tokens in the row's names, or the leaf as
    a prefix. A row keeps its best tier, and within a tier a row whose
    context also matches the query's context comes first.
    """
    prior = hierarchy_prior_sql("a.subtype")
    context_hit = _CONTEXT_HIT if with_context else "false"
    order = _order_within_tier(prior, with_context)
    filters = _live_filters(requested)
    leaf_query = (
        f"to_tsquery('{TS_CONFIG}', :leaf_query)"
        if stage == "retry"
        else f"plainto_tsquery('{TS_CONFIG}', :leaf)"
    )
    vector = "a.search_tsv" if stage == "fallback" else "a.name_tsv"

    def arm(tier: int, match: str, join: str = "") -> str:
        return _arm(tier, match, filters=filters, order=order, join=join)

    arms = []
    if stage == "typed":
        # The leaf from the covering index, then the variants table.
        arms.append(arm(EXACT_TIER, "a.leaf_norm = :leaf_norm"))
        arms.append(
            arm(
                EXACT_TIER,
                "n.name_norm = :leaf_norm",
                "JOIN aoi_names n ON n.aoi_id = a.id",
            )
        )
    arms.append(arm(PARTIAL_TIER, f"{vector} @@ q.lq"))
    if stage == "typed":
        arms.append(arm(PARTIAL_TIER, "a.leaf_norm LIKE :leaf_prefix"))

    return _tiered_statement(
        queries=f"""
                {leaf_query} AS lq,
                CASE WHEN :context <> ''
                     THEN plainto_tsquery('{TS_CONFIG}', :context)
                END AS cq""",
        arms=arms,
        score=f"""round(
                ((b.tier / {EXACT_TIER}.0) * {_SCORE_TIER_WEIGHT}
                 + ({context_hit})::int * {_SCORE_CONTEXT_WEIGHT}
                 + {prior} * {_SCORE_PRIOR_WEIGHT}) * :scale, 4
            )::double precision""",
        corrected=str(stage == "retry").lower(),
        extra_columns=f",\n            {context_hit} AS context_hit",
        order=order,
        paging="LIMIT :limit OFFSET :offset",
    )


_LEAF_PREFIX_HIT = "(a.leaf_norm LIKE :leaf_prefix) IS TRUE"


def _order_autocomplete(prior: str) -> str:
    return ", ".join(
        [f"{prior} DESC", f"{_LEAF_PREFIX_HIT} DESC", *_TIE_BREAK]
    )


def _prefix_tsquery(lexemes: Optional[list[str]]) -> Optional[str]:
    """A tsquery string that ANDs *lexemes*, the last one as a prefix.

    "bangalore ur" becomes ``'bangalore' & 'ur':*``, which is how a partly
    typed last word completes. None when there are no lexemes.
    """
    if not lexemes:
        return None
    quoted = [_tsquery_lexeme(lexeme) for lexeme in lexemes]
    quoted[-1] += ":*"
    return " & ".join(quoted)


# The token arm expands the last typed word to every stored lexeme with that
# prefix. Two or three letters expand to thousands of lexemes and take
# seconds, and add nothing the leaf-prefix arms do not already find for a
# single word. So a lone word gets the token arm only once it is this long
# ("york" reaches New York); several words always get it ("new y").
_AUTOCOMPLETE_TOKEN_MIN_CHARS = 4


def _autocomplete_token_query(lexemes: Optional[list[str]]) -> str:
    if not lexemes:
        return ""
    if len(lexemes) == 1 and len(lexemes[0]) < _AUTOCOMPLETE_TOKEN_MIN_CHARS:
        return ""
    return _prefix_tsquery(lexemes) or ""


def _autocomplete_sql(
    requested: set[str], *, with_tokens: bool, with_context: bool
) -> str:
    """The typeahead statement: what the typed text is the start of.

    Tier 2 is a prefix of the leaf or of any stored name variant; tier 1,
    when *with_tokens*, is the typed words as tokens with the last one as a
    prefix, so "bangalore ur" completes to Bangalore Urban. A typed parent
    ("Paris, Fr") filters every arm by its own prefix query. Ordered by the
    hierarchy prior first, since a keystroke list should lead with the
    prominent places, then a leaf prefix over a variant's. No typo
    correction: the next keystroke is the correction.
    """
    prior = hierarchy_prior_sql("a.subtype")
    order = _order_autocomplete(prior)
    # The context filter is emitted only when a parent was typed: the prefix
    # arms otherwise touch no column outside the covering index, so a short
    # prefix that matches tens of thousands of rows is sorted from the index
    # alone, without a heap fetch per row.
    context_filter = "a.search_tsv @@ q.cq AND " if with_context else ""
    filters = context_filter + _live_filters(requested)

    def arm(tier: int, match: str, join: str = "") -> str:
        return _arm(tier, match, filters=filters, order=order, join=join)

    # A semi-join, not a join: an AOI with several variants starting the
    # same way (Lisboa: Lisbon, Lisbonne, Lissabon) takes one slot of the
    # arm's k, which is what keeps the per-arm cut exact.
    arms = [
        arm(EXACT_TIER, "a.leaf_norm LIKE :leaf_prefix"),
        arm(
            EXACT_TIER,
            "EXISTS (SELECT 1 FROM aoi_names n WHERE n.aoi_id = a.id "
            "AND n.name_norm LIKE :leaf_prefix)",
        ),
    ]
    if with_tokens:
        arms.append(arm(PARTIAL_TIER, "a.name_tsv @@ q.lq"))

    return _tiered_statement(
        queries=f"""
                CASE WHEN :leaf_query <> ''
                     THEN to_tsquery('{TS_CONFIG}', :leaf_query)
                END AS lq,
                CASE WHEN :context_query <> ''
                     THEN to_tsquery('{TS_CONFIG}', :context_query)
                END AS cq""",
        arms=arms,
        score=f"""round(
                (b.tier / {EXACT_TIER}.0) * {_AUTOCOMPLETE_TIER_WEIGHT}
                + {prior} * {_AUTOCOMPLETE_PRIOR_WEIGHT}, 4
            )::double precision""",
        corrected="false",
        extra_columns=",\n            false AS context_hit",
        order=order,
        paging="LIMIT :limit",
    )


def _browse_sql(requested: set[str]) -> str:
    """The no-name statement: every live row in the asked sources, by name."""
    return f"""
        SELECT {_RESULT_COLUMNS},
            NULL::int AS tier,
            a.leaf,
            false AS corrected,
            false AS context_hit
        FROM aois a
        WHERE {_live_filters(requested)}
        ORDER BY a.name, a.source, a.source_id
        LIMIT :limit OFFSET :offset
    """


# The miss path. When nothing matches as typed, one statement looks every
# word of the leaf up in the token table: how many names carry it, and the
# stored tokens nearest to it. Nearest means within the trigram threshold (the
# GIN index gate), then by edit distance, then by the prominence of the
# best-known place carrying the token ("paolo" is São Paulo's "paulo" before
# a village's "palo"), then by how many names carry it; and only at a
# distance small for the word ("kashmir" is not "kashmore"). Words under
# ``_CORRECTION_MIN_CHARS`` have too few trigrams to correct and pass
# through unchanged.
_CORRECTION_MIN_CHARS = 3
# pg_trgm's similarity gate for a stored token to count as a neighbour at
# all; set for the transaction only.
_CORRECTION_TRGM_THRESHOLD = 0.3
# Neighbours kept per word, and the edit budget: one edit per this many
# letters of the word, and at least one.
_CORRECTION_NEAREST = 3
_CORRECTION_CHARS_PER_EDIT = 4
# levenshtein() refuses input over 255 characters, so a longer token or word
# is left out instead of failing the lookup.
_LEVENSHTEIN_MAX_CHARS = 255
_LEAF_TOKENS_SQL = f"""
    SELECT t.lexeme,
           COALESCE(own.ndoc, 0),
           array_agg(c.token
                     ORDER BY c.dist, c.prominence DESC, c.ndoc DESC, c.token)
               FILTER (WHERE c.token IS NOT NULL),
           array_agg(c.dist
                     ORDER BY c.dist, c.prominence DESC, c.ndoc DESC, c.token)
               FILTER (WHERE c.token IS NOT NULL)
    FROM unnest(to_tsvector('{TS_CONFIG}', :leaf)) AS t(lexeme, positions, weights)
    LEFT JOIN aoi_search_tokens own ON own.token = t.lexeme
    LEFT JOIN LATERAL (
        SELECT token, ndoc, prominence, dist
        FROM (
            SELECT token, ndoc, prominence,
                   CASE WHEN length(token) <= :max_chars
                        THEN levenshtein(token, t.lexeme) END AS dist
            FROM aoi_search_tokens
            WHERE length(t.lexeme) BETWEEN :min_chars AND :max_chars
              AND token % t.lexeme
        ) s
        WHERE dist <= greatest(1, length(t.lexeme) / :chars_per_edit)
        ORDER BY dist, prominence DESC, ndoc DESC, token
        LIMIT :nearest
    ) c ON true
    WHERE t.lexeme NOT LIKE '%-%'
    GROUP BY t.lexeme, own.ndoc
    ORDER BY min((t.positions)[1])
"""
# set_config with is_local, the parameterised form of SET LOCAL.
_CORRECTION_THRESHOLD_SQL = (
    "SELECT set_config('pg_trgm.similarity_threshold', :threshold, true)"
)
# A word in more names than this ("new", "park", "sao", "republic") does not
# name a place on its own, so a retry that keeps only such words is skipped.
_COMMON_TOKEN_NDOC = 1000
# A corrected result ranks below what an uncorrected query would have found;
# a partial match (one word dropped) sits below a corrected one, because a
# small misspelling is a closer reading of the input than a missing word.
_CORRECTED_SCORE_SCALE = 0.8
_PARTIAL_SCORE_SCALE = 0.6


def _tsquery_lexeme(token: str) -> str:
    return "'" + token.replace("\\", "\\\\").replace("'", "''") + "'"


@dataclass(frozen=True)
class _LeafToken:
    """One word of the leaf as the token table knows it."""

    lexeme: str
    ndoc: int  # names carrying the word as typed; 0 when none does
    nearest: tuple[str, ...]  # stored tokens by edit distance, self first
    distances: tuple[int, ...]  # the edit distance of each, same order

    def within(self, max_distance: int) -> tuple[str, ...]:
        return tuple(
            token
            for token, distance in zip(self.nearest, self.distances)
            if distance <= max_distance
        )


async def _leaf_tokens(conn, leaf: str) -> Optional[list[_LeafToken]]:
    """Look the words of *leaf* up, or None when there are none.

    The caller has already bounded the word count (``_MAX_MISS_LEXEMES``)
    from the lexemes it bound, so this lookup never runs over a long phrase.
    """
    await conn.execute(
        text(_CORRECTION_THRESHOLD_SQL),
        {"threshold": str(_CORRECTION_TRGM_THRESHOLD)},
    )
    rows = (
        await conn.execute(
            text(_LEAF_TOKENS_SQL),
            {
                "leaf": leaf,
                "min_chars": _CORRECTION_MIN_CHARS,
                "max_chars": _LEVENSHTEIN_MAX_CHARS,
                "chars_per_edit": _CORRECTION_CHARS_PER_EDIT,
                "nearest": _CORRECTION_NEAREST,
            },
        )
    ).all()
    if not rows:
        return None
    return [
        _LeafToken(lexeme, ndoc, tuple(nearest or ()), tuple(distances or ()))
        for lexeme, ndoc, nearest, distances in rows
    ]


def _corrected_query(
    tokens: list[_LeafToken], max_distance: Optional[int]
) -> Optional[str]:
    """A tsquery over the stored tokens near each word, within
    *max_distance* edits (None: every neighbour the lookup kept).

    Returns None when no word has a neighbour other than itself (the query
    would repeat the one that missed) or when a word of correctable length
    has no stored token near it: the groups are ANDed, so one empty group
    can match nothing.
    """
    groups = []
    changed = False
    for token in tokens:
        near = (
            token.nearest
            if max_distance is None
            else token.within(max_distance)
        )
        if near:
            groups.append("(" + " | ".join(map(_tsquery_lexeme, near)) + ")")
            changed |= near != (token.lexeme,)
        elif len(token.lexeme) < _CORRECTION_MIN_CHARS:
            groups.append(_tsquery_lexeme(token.lexeme))
        else:
            return None
    return " & ".join(groups) if changed else None


def _corrected_queries(tokens: list[_LeafToken]) -> list[str]:
    """The corrected queries to try, nearest first.

    One edit away first, then everything the lookup kept: a two-edit
    neighbour of a prominent place ("bangora" for "banglore", from
    Bamingui-Bangoran) must not outrank the one-edit correction
    ("bangalore") just because the retry ranks by prominence.
    """
    queries = [
        query
        for query in (
            _corrected_query(tokens, 1),
            _corrected_query(tokens, None),
        )
        if query
    ]
    return list(dict.fromkeys(queries))


def _names_a_place(kept: list[_LeafToken]) -> bool:
    """Whether a retry over *kept* can return what the user asked for.

    The retry ANDs the kept words against the name vector, so every one of
    them must be in some name or the query cannot match. Two or more words
    together are then selective enough. One word on its own is not when the
    corpus has it everywhere ("republic", "sao") or it is too short to be a
    name ("np").
    """
    if not all(token.ndoc for token in kept):
        return False
    if len(kept) > 1:
        return True
    (token,) = kept
    return (
        len(token.lexeme) >= _CORRECTION_MIN_CHARS
        and token.ndoc <= _COMMON_TOKEN_NDOC
    )


def _reduced_queries(tokens: list[_LeafToken]) -> list[str]:
    """The words with one dropped: the last, then the first.

    An extra generic word ("Serengeti NP", "Ho Chi Minh City") makes the
    all-words query miss; a place name rarely has more than one such word,
    so two retries cover it. A retry whose remaining words cannot name a
    place ("republic" from "Czech Republic") is skipped.
    """
    if len(tokens) < 2:
        return []
    queries = []
    for kept in (tokens[:-1], tokens[1:]):
        if _names_a_place(kept):
            queries.append(
                " & ".join(_tsquery_lexeme(token.lexeme) for token in kept)
            )
    return list(dict.fromkeys(queries))


def _satisfies(result: pd.DataFrame, parsed: SearchText) -> bool:
    """Whether *result* answers the query as typed.

    An empty frame does not. Neither does one where the query named a parent
    and no row has it: "Lisbon, Portugal" must not stop at the US preserves
    called Lisbon when a correction would reach Lisboa.
    """
    if result.empty:
        return False
    if parsed.context and not result["context_hit"].any():
        return False
    return True


def _validate_request(
    name: Optional[str],
    parsed: SearchText,
    limit: int,
    offset: int,
    mode: SearchMode,
) -> None:
    """Reject input the search cannot or must not serve.

    One place for every rule, so the API and the geocoder cannot disagree
    about what is valid. The API maps the error to 422.
    """
    if name is not None:
        if len(name) > MAX_SEARCH_NAME_CHARS:
            raise SearchRequestError(
                f"name is longer than {MAX_SEARCH_NAME_CHARS} characters"
            )
        if "\x00" in name:
            raise SearchRequestError("name contains a NUL character")
    if limit < 1:
        raise SearchRequestError("limit must be at least 1")
    if not 0 <= offset <= MAX_SEARCH_OFFSET:
        raise SearchRequestError(
            f"offset must be between 0 and {MAX_SEARCH_OFFSET}"
        )
    if mode == "autocomplete":
        if len(parsed.leaf) < AUTOCOMPLETE_MIN_CHARS:
            raise SearchRequestError(
                f"autocomplete needs a name of at least "
                f"{AUTOCOMPLETE_MIN_CHARS} characters"
            )
        if offset:
            raise SearchRequestError("autocomplete does not accept offset")


async def search_aois(
    name: Optional[str],
    sources: Optional[list[str]],
    user_id: Optional[str],
    limit: int = 50,
    offset: int = 0,
    mode: SearchMode = "search",
) -> pd.DataFrame:
    """Search AOIs across sources by name and/or source type.

    This is the shared search core reused by both the agent's ``pick_aoi``
    geocoder (via :func:`query_aoi_database`) and the ``GET /api/aois``
    endpoint. docs/aoi-full-text-search.md describes the tiers.

    Args:
        name: Text to search for, "Place" or "Place, Parent". When
            empty/None the query runs in *browse* mode: no name filter,
            ordered alphabetically.
        sources: Subset of canonical source keys (gadm/kba/wdpa/landmark/custom)
            to search; ``None`` searches every source. Aliases such as
            ``protectedareas`` are accepted and normalized.
        user_id: Owner used to scope custom areas. Required when ``custom`` is
            among the searched sources.
        limit: Maximum number of rows to return.
        offset: Number of rows to skip (offset pagination).
        mode: ``search`` resolves a name; ``autocomplete`` completes what
            has been typed so far (a prefix of a name, or the typed words
            with the last one as a prefix), needs at least
            ``AUTOCOMPLETE_MIN_CHARS`` characters, takes no offset and never
            corrects a typo.

    Returns:
        DataFrame with columns ``src_id, name, subtype, source, bbox, tier,
        leaf, corrected, context_hit`` (plus ``similarity_score`` when
        searching by name). ``tier`` is ``EXACT_TIER`` for a row whose leaf
        or a stored variant equals the query, ``PARTIAL_TIER`` for a token
        or prefix match, and null when browsing. ``similarity_score`` in
        [0, 1] summarises the rank (the tier, whether the query's parent
        matched, and the hierarchy prior, scaled down on the miss path) for
        callers that need one number; it is not the sort key, which also
        breaks ties on an exact leaf and on area, so rows with equal scores
        can come back in either order.
        ``leaf`` is the place's own stored name, which a caller comparing
        names should use rather than splitting ``name`` at its first comma.
        ``corrected`` is True for a row the miss path found, after correcting
        the spelling or dropping a word, so a caller can treat it as a guess.
        ``context_hit`` is True when the query named a parent and the row
        has it, so a caller re-ranking rows can honour the parent the user
        typed. Disputed and deprecated AOIs are excluded, and a custom area
        appears only for its owner.

        Paging and the miss path interact: an empty page counts as a miss,
        so an offset past the end of the as-typed result falls through to
        the fallback and corrected queries and returns their rows at that
        offset. Page two of a corrected result exists because of this, but
        so does a page two of typed results followed by corrected rows. The
        API's callers page short lists, so this is left as is.

    Raises:
        SearchRequestError: For input the search will not serve: a name over
            ``MAX_SEARCH_NAME_CHARS`` or holding a NUL, a limit under 1, an
            offset outside ``0..MAX_SEARCH_OFFSET``, or an autocomplete with
            too short a name or a non-zero offset.
        ValueError: For an invalid source, or for a missing ``user_id`` when
            ``custom`` is searched.
    """
    if sources:
        requested = {normalize_aoi_source(s) for s in sources}
    else:
        requested = set(VALID_AOI_SOURCES)

    if "custom" in requested and not user_id:
        raise ValueError("user_id required for custom areas")

    parsed = parse_search_text(name or "")
    _validate_request(name, parsed, limit, offset, mode)

    params: Dict[str, Any] = {
        "sources": sorted(requested),
        "limit": limit,
        "offset": offset,
    }
    if "custom" in requested:
        params["user_id"] = user_id

    async with get_connection_from_pool() as conn:
        try:
            if not parsed.leaf:
                return await _browse(conn, requested, params)
            leaf_lexemes, context_lexemes = await _bind_leaf(
                conn, parsed, params
            )
            if mode == "autocomplete":
                return await _autocomplete(
                    conn, requested, params, leaf_lexemes, context_lexemes
                )
            return await _search_with_retries(
                conn, requested, parsed, params, leaf_lexemes
            )
        finally:
            # Read-only, and the miss path's threshold was SET LOCAL: end the
            # transaction so the pooled connection carries nothing over.
            await conn.rollback()


async def _read(conn, sql_query: str, params: Dict[str, Any]) -> pd.DataFrame:
    return await conn.run_sync(
        lambda sync_conn: pd.read_sql(
            text(sql_query), sync_conn, params=params
        )
    )


async def _browse(conn, requested: set[str], params: Dict[str, Any]):
    return await _read(conn, _browse_sql(requested), params)


async def _bind_leaf(
    conn, parsed: SearchText, params: Dict[str, Any]
) -> tuple[Optional[list[str]], Optional[list[str]]]:
    """Bind the leaf, its normalized form and its LIKE prefix as constants.

    Returns the leaf's and the context's lexemes, which autocomplete turns
    into prefix queries.
    """
    params.update(
        {
            "leaf": parsed.leaf,
            "context": parsed.context,
            "k": params["limit"] + params["offset"],
            "scale": 1.0,
        }
    )
    row = (
        await conn.execute(
            text(_NORMALIZE_LEAF_SQL),
            {"leaf": parsed.leaf, "context": parsed.context},
        )
    ).one()
    (
        params["leaf_norm"],
        params["leaf_prefix"],
        leaf_lexemes,
        context_lexemes,
    ) = row
    return leaf_lexemes, context_lexemes


async def _autocomplete(
    conn,
    requested: set[str],
    params: Dict[str, Any],
    leaf_lexemes: Optional[list[str]],
    context_lexemes: Optional[list[str]],
) -> pd.DataFrame:
    params["leaf_query"] = _autocomplete_token_query(leaf_lexemes)
    params["context_query"] = _prefix_tsquery(context_lexemes) or ""
    statement = _autocomplete_sql(
        requested,
        with_tokens=bool(params["leaf_query"]),
        with_context=bool(params["context_query"]),
    )
    return await _read(conn, statement, params)


async def _search_with_retries(
    conn,
    requested: set[str],
    parsed: SearchText,
    params: Dict[str, Any],
    leaf_lexemes: Optional[list[str]],
) -> pd.DataFrame:
    """The query as typed, then the miss path, stopping at the first result
    that answers the query. Each step is one more round trip, only on a
    miss."""
    with_context = bool(parsed.context)

    def statement(stage: _SearchStage) -> str:
        return _search_sql(requested, stage=stage, with_context=with_context)

    result = await _read(conn, statement("typed"), params)
    if _satisfies(result, parsed):
        return result

    # The words may be spread over name and context ("Bristol England"):
    # try the full vector.
    fallback = await _read(conn, statement("fallback"), params)
    if _satisfies(fallback, parsed):
        return fallback

    # A phrase of many words is not a place name to correct, and the lookup
    # costs one trigram query per word: decide before running it.
    if not leaf_lexemes or len(leaf_lexemes) > _MAX_MISS_LEXEMES:
        return result
    # Look the words up once, then retry with the spelling corrected and
    # with one word dropped.
    tokens = await _leaf_tokens(conn, parsed.leaf)
    if tokens is None:
        return result
    retries = [
        (query, _CORRECTED_SCORE_SCALE) for query in _corrected_queries(tokens)
    ]
    retries += [
        (query, _PARTIAL_SCORE_SCALE) for query in _reduced_queries(tokens)
    ]
    token_statement = statement("retry")
    for params["leaf_query"], params["scale"] in retries:
        retried = await _read(conn, token_statement, params)
        if _satisfies(retried, parsed):
            return retried
    return result
