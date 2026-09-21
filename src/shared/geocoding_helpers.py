import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional, Union
from uuid import UUID

import pandas as pd
from sqlalchemy import select, text

from src.api.data_models import CustomAreaOrm
from src.shared.aoi_search_sql import TS_CONFIG, norm_sql
from src.shared.database import (
    get_connection_from_pool,
    get_session_from_pool,
)
from src.shared.logging_config import get_logger
from src.shared.request_context import current_user_id

logger = get_logger(__name__)

SUBREGION_TO_SUBTYPE_MAPPING = {
    "country": "country",
    "state": "state-province",
    "district": "district-county",
    "municipality": "municipality",
    "locality": "locality",
    "neighbourhood": "neighbourhood",
    "kba": "key-biodiversity-area",
    "wdpa": "protected-area",
    "landmark": "indigenous-and-community-land",
    "custom": "custom-area",
}


# The id column that each source used before the AOI tables were unified.
# `aois.source_id` now holds every id as text, so no read path resolves an AOI
# through these names. Three places still need them:
#   * `GET /api/metadata` returns them as `layer_id_mapping`. The frontend uses
#     it to address tile layers, so this is a public contract.
#   * Subregion expansion and the global-country query return the id under its
#     source-specific name, for the same mapping.
#   * The ingest scripts use the name to name their indexes.
AOI_SOURCE_ID_COLUMNS = {
    "kba": "sitrecid",
    "landmark": "landmark_id",
    "wdpa": "wdpa_pid",
    "gadm": "gadm_id",
    "custom": "id",
}


# The table that holds each source's raw rows. `build-aois` transforms them into
# `aois`. Only that command reads these tables. No API or agent path reads them.
# Their future is not decided (see docs/aoi-architecture).
SOURCE_STAGING_TABLES = {
    "kba": "geometries_kba",
    "landmark": "geometries_landmark",
    "wdpa": "geometries_wdpa",
    "gadm": "geometries_gadm",
    "custom": "custom_areas",
}


# GADM LEVELS. `col_name` is the level's id column in GADM's own files,
# `name_col` the column holding that level's name. Level 0 is the exception
# GADM calls COUNTRY rather than NAME_0, which is why `name_col` is declared
# per level instead of derived from `col_name` by the callers that need it.
GADM_LEVELS = {
    "country": {"col_name": "GID_0", "name_col": "COUNTRY", "name": "iso"},
    "state-province": {
        "col_name": "GID_1",
        "name_col": "NAME_1",
        "name": "adm1",
    },
    "district-county": {
        "col_name": "GID_2",
        "name_col": "NAME_2",
        "name": "adm2",
    },
    "municipality": {
        "col_name": "GID_3",
        "name_col": "NAME_3",
        "name": "adm3",
    },
    "locality": {"col_name": "GID_4", "name_col": "NAME_4", "name": "adm4"},
    "neighbourhood": {
        "col_name": "GID_5",
        "name_col": "NAME_5",
        "name": "adm5",
    },
}

GADM_SUBTYPE_MAP = {val["col_name"]: key for key, val in GADM_LEVELS.items()}

# Matches standard GADM IDs (3-letter ISO prefix): "USA", "BRA.16_1", "IND.12.26_1", etc.
# Excludes disputed-territory codes like "Z01", "Z02" which downstream APIs reject.
GADM_STANDARD_ID_RE = r"^[A-Z]{3}"


# Friendly source aliases accepted from callers (e.g. the search API) and
# mapped onto the canonical source keys.
SOURCE_ALIASES = {
    "protectedareas": "wdpa",
    "protected_areas": "wdpa",
    "protected-areas": "wdpa",
}

VALID_AOI_SOURCES = set(AOI_SOURCE_ID_COLUMNS.keys())


def normalize_aoi_source(source: str) -> str:
    """Map a (possibly aliased) source name onto a canonical source key."""
    key = SOURCE_ALIASES.get(source.lower(), source.lower())
    if key not in VALID_AOI_SOURCES:
        raise ValueError(
            f"Invalid source: {source}. Must be one of: "
            f"{', '.join(sorted(VALID_AOI_SOURCES))}"
        )
    return key


# The default bbox when an AOI has no bbox, or no row. AOIIndex and
# aoi_selection use the same default.
WORLD_BBOX = [-180.0, -90.0, 180.0, 90.0]


# Preference by subtype: broader admin units beat narrower ones, and admin
# units beat named sites (KBA/WDPA/Landmark), so a bare "Lisbon" resolves to
# the Portuguese district rather than a small "Lisbon Forest Preserve". Search
# ranks with it in SQL and the geocoder's scorer re-uses it in Python. The
# weights are tuning constants, hand-authored.
HIERARCHY_SCORES: dict[str, float] = {
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

# A subtype missing from the map would rank as 0 in SQL and raise in the
# scorer, so pin the coverage at import time.
assert set(HIERARCHY_SCORES) == set(SUBREGION_TO_SUBTYPE_MAPPING.values())


def hierarchy_prior_sql(subtype_expr: str) -> str:
    """``HIERARCHY_SCORES`` as a SQL CASE over *subtype_expr*, in [0, 1]."""
    arms = " ".join(
        f"WHEN '{subtype}' THEN {score}"
        for subtype, score in HIERARCHY_SCORES.items()
    )
    return f"(CASE {subtype_expr} {arms} ELSE 0.0 END)"


# An `aoi_choice` nudge option is resubmitted verbatim as the next question:
# "Paris, Île-de-France, France - (district-county) [FRA]". The trailing
# decoration is not part of any name.
_NUDGE_DECORATION_RE = re.compile(r"\s+-\s+\([^)]*\)\s*\[[A-Za-z]{3}\]\s*$")


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

    The geocoder and the nudge both send "Place, Parent" strings, and the
    stored names are comma-joined most-specific-first, so the first segment
    is the place and the rest is where it is. A segment of only whitespace
    is dropped.
    """
    stripped = _NUDGE_DECORATION_RE.sub("", name.strip())
    segments = [s.strip() for s in stripped.split(",")]
    segments = [s for s in segments if s]
    if not segments:
        return SearchText("", "")
    return SearchText(segments[0], " ".join(segments[1:]))


# The order within a tier: a context hit first (the query named the parent
# and this row has it), then the hierarchy prior, then a match on the
# primary name over one on a variant ("Lisbon" is Lisboa before a US
# preserve called Lisbon, because the prior outranks the primary-name key),
# the larger area, and a stable name/id tie-break. Booleans are compared IS
# TRUE so a NULL leaf or context sorts as false rather than first. Every
# candidate arm sorts by the same keys, which is what makes a per-arm LIMIT
# exact: a row in the final top-N with best tier t sits within the top-N of
# arm t, because every row above it in that arm also ranks above it in the
# result.
_CONTEXT_HIT = "(q.cq IS NOT NULL AND a.search_tsv @@ q.cq) IS TRUE"
_EXACT_LEAF = "(a.leaf_norm = :leaf_norm) IS TRUE"
_ORDER_WITHIN_TIER = (
    f"{{context_hit}} DESC, {{prior}} DESC, {_EXACT_LEAF} DESC, "
    "a.area_km2 DESC NULLS LAST, a.name, a.source, a.source_id"
)

# The normalized leaf and its LIKE prefix are bound as constants, computed by
# this statement first: a LIKE whose pattern is a column cannot become an
# index range, and the same normalization must apply to the query as to the
# stored names. The prefix escapes LIKE's wildcards.
_NORMALIZE_LEAF_SQL = f"""
    SELECT n,
           replace(replace(replace(n, '\\', '\\\\'), '%', '\\%'), '_', '\\_')
             || '%',
           (SELECT array_agg(lexeme ORDER BY positions[1])
            FROM unnest(to_tsvector('{TS_CONFIG}', :leaf))),
           (SELECT array_agg(lexeme ORDER BY positions[1])
            FROM unnest(to_tsvector('{TS_CONFIG}', :context)))
    FROM (SELECT {norm_sql(":leaf")} AS n) s
"""

SearchMode = Literal["search", "autocomplete"]

# Autocomplete answers a keystroke, so it needs a couple of characters to
# have anything to complete, and it pages nothing: the next keystroke
# replaces the list.
AUTOCOMPLETE_MIN_CHARS = 2


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


def _search_sql(
    requested: set[str], *, corrected: bool, with_context: bool
) -> str:
    """The tiered search statement. See docs/aoi-full-text-search.md.

    Tier 2 is an exact match on any stored name variant; tier 1 is a partial
    match, the leaf tokens anywhere in the name or the leaf as a prefix. A
    row keeps its best tier, and within a tier a row whose context also
    matches the query's context comes first. With *corrected* the leaf
    tokens come from the typo correction as a prepared tsquery and only the
    token arm runs: an exact or prefix match would already have been found.
    """
    prior = hierarchy_prior_sql("a.subtype")
    # Without a typed context the context-hit key is a constant, which keeps
    # the exact and prefix arms free of any column outside the covering
    # index (see idx_aois_leaf_norm).
    # An expression, not a literal: Postgres rejects a constant in ORDER BY.
    context_hit = _CONTEXT_HIT if with_context else "(1 = 0)"
    order = _ORDER_WITHIN_TIER.format(prior=prior, context_hit=context_hit)
    filters = (
        "NOT a.is_disputed AND NOT a.is_deprecated "
        "AND a.source = ANY(:sources)" + _custom_scope_sql(requested)
    )
    leaf_query = (
        f"to_tsquery('{TS_CONFIG}', :leaf_query)"
        if corrected
        else f"plainto_tsquery('{TS_CONFIG}', :leaf)"
    )

    def arm(tier: int, match: str, join: str = "") -> str:
        return (
            f"(SELECT a.id, {tier} AS tier FROM aois a {join}, q "
            f"WHERE {match} AND {filters} ORDER BY {order} LIMIT :k)"
        )

    arms = []
    if not corrected:
        arms.append(
            arm(
                2,
                "n.name_norm = :leaf_norm",
                "JOIN aoi_names n ON n.aoi_id = a.id",
            )
        )
    arms.append(arm(1, "a.search_tsv @@ q.lq"))
    if not corrected:
        arms.append(arm(1, "a.leaf_norm LIKE :leaf_prefix"))

    return f"""
        WITH q AS (
            SELECT
                {leaf_query} AS lq,
                CASE WHEN :context <> ''
                     THEN plainto_tsquery('{TS_CONFIG}', :context)
                END AS cq
        ),
        cand AS ({" UNION ALL ".join(arms)}),
        best AS (SELECT id, max(tier) AS tier FROM cand GROUP BY id)
        SELECT
            a.source_id AS src_id,
            a.name,
            a.subtype,
            a.source,
            COALESCE(
                a.bbox, ARRAY[-180, -90, 180, 90]::double precision[]
            ) AS bbox,
            round(
                ((b.tier / 2.0) * 0.55
                 + ({context_hit})::int * 0.2
                 + {prior} * 0.25) * :scale, 4
            )::double precision AS similarity_score,
            {context_hit} AS context_hit
        FROM best b
        JOIN aois a ON a.id = b.id, q
        ORDER BY b.tier DESC, {order}
        LIMIT :limit OFFSET :offset
    """


_LEAF_PREFIX_HIT = "(a.leaf_norm LIKE :leaf_prefix) IS TRUE"
_ORDER_AUTOCOMPLETE = (
    "{prior} DESC, " + _LEAF_PREFIX_HIT + " DESC, "
    "a.area_km2 DESC NULLS LAST, a.name, a.source, a.source_id"
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
    prominent places, then a primary-name prefix over a variant's. No typo
    correction: the next keystroke is the correction.
    """
    prior = hierarchy_prior_sql("a.subtype")
    order = _ORDER_AUTOCOMPLETE.format(prior=prior)
    # The context filter is emitted only when a parent was typed: the prefix
    # arms otherwise touch no column outside the covering index, so a short
    # prefix that matches tens of thousands of rows is sorted from the index
    # alone, without a heap fetch per row.
    context_filter = "a.search_tsv @@ q.cq AND " if with_context else ""
    filters = (
        f"{context_filter}"
        "NOT a.is_disputed AND NOT a.is_deprecated "
        "AND a.source = ANY(:sources)" + _custom_scope_sql(requested)
    )

    def arm(tier: int, match: str, join: str = "") -> str:
        return (
            f"(SELECT a.id, {tier} AS tier FROM aois a {join}, q "
            f"WHERE {match} AND {filters} ORDER BY {order} LIMIT :k)"
        )

    arms = [
        arm(2, "a.leaf_norm LIKE :leaf_prefix"),
        # Primary names are the leaf arm above; only the variants are new.
        arm(
            2,
            "n.kind <> 'primary' AND n.name_norm LIKE :leaf_prefix",
            "JOIN aoi_names n ON n.aoi_id = a.id",
        ),
    ]
    if with_tokens:
        arms.append(arm(1, "a.search_tsv @@ q.lq"))
    return f"""
        WITH q AS (
            SELECT
                CASE WHEN :leaf_query <> ''
                     THEN to_tsquery('{TS_CONFIG}', :leaf_query)
                END AS lq,
                CASE WHEN :context_query <> ''
                     THEN to_tsquery('{TS_CONFIG}', :context_query)
                END AS cq
        ),
        cand AS ({" UNION ALL ".join(arms)}),
        best AS (SELECT id, max(tier) AS tier FROM cand GROUP BY id)
        SELECT
            a.source_id AS src_id,
            a.name,
            a.subtype,
            a.source,
            COALESCE(
                a.bbox, ARRAY[-180, -90, 180, 90]::double precision[]
            ) AS bbox,
            round(
                (b.tier / 2.0) * 0.5 + {prior} * 0.5, 4
            )::double precision AS similarity_score
        FROM best b
        JOIN aois a ON a.id = b.id, q
        ORDER BY b.tier DESC, {order}
        LIMIT :limit
    """


_BROWSE_SQL = """
    SELECT
        a.source_id AS src_id,
        a.name,
        a.subtype,
        a.source,
        COALESCE(
            a.bbox, ARRAY[-180, -90, 180, 90]::double precision[]
        ) AS bbox
    FROM aois a
    WHERE NOT a.is_disputed
      AND NOT a.is_deprecated
      AND a.source = ANY(:sources)
      {custom_scope}
    ORDER BY a.name, a.source, a.source_id
    LIMIT :limit OFFSET :offset
"""

# Typo correction. A query token that no stored name contains is replaced by
# the stored tokens nearest to it by trigram similarity, most frequent first
# among equals. The GIN trigram index on the token table serves `%`; the
# threshold is set for the transaction only.
_LEAF_TOKENS_SQL = f"""
    SELECT DISTINCT lexeme FROM unnest(to_tsvector('{TS_CONFIG}', :leaf))
"""
_TOKEN_CORRECTIONS_SQL = """
    SELECT token FROM aoi_search_tokens
    WHERE token % :tok
    ORDER BY similarity(token, :tok) DESC, ndoc DESC, token
    LIMIT 3
"""
_CORRECTION_THRESHOLD_SQL = "SET LOCAL pg_trgm.similarity_threshold = 0.3"
# A corrected result ranks below what an uncorrected query would have found.
_CORRECTED_SCORE_SCALE = 0.6


def _tsquery_lexeme(token: str) -> str:
    return "'" + token.replace("\\", "\\\\").replace("'", "''") + "'"


async def _corrected_leaf_query(conn, leaf: str) -> Optional[str]:
    """A tsquery over the nearest stored tokens for each token of *leaf*.

    Returns None when *leaf* has no tokens or when some token has no stored
    token near it: the query ANDs the groups, so one empty group can match
    nothing.
    """
    rows = await conn.execute(text(_LEAF_TOKENS_SQL), {"leaf": leaf})
    tokens = [row[0] for row in rows]
    if not tokens:
        return None
    await conn.execute(text(_CORRECTION_THRESHOLD_SQL))
    groups = []
    for token in tokens:
        rows = await conn.execute(text(_TOKEN_CORRECTIONS_SQL), {"tok": token})
        nearest = [row[0] for row in rows]
        if not nearest:
            return None
        groups.append("(" + " | ".join(map(_tsquery_lexeme, nearest)) + ")")
    return " & ".join(groups)


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
        DataFrame with columns ``src_id, name, subtype, source, bbox`` (plus
        ``similarity_score`` in [0, 1] when searching by name: the match
        tier, whether the query's parent matched, and the hierarchy prior,
        scaled down for a typo-corrected match). Disputed and deprecated
        AOIs are excluded, and a custom area appears only for its owner.

    Raises:
        ValueError: For an invalid source, for a missing ``user_id`` when
            ``custom`` is searched, or for an autocomplete with too short a
            name or a non-zero offset.
    """
    if sources:
        requested = {normalize_aoi_source(s) for s in sources}
    else:
        requested = set(VALID_AOI_SOURCES)

    if "custom" in requested and not user_id:
        raise ValueError("user_id required for custom areas")

    params: Dict[str, Any] = {
        "sources": sorted(requested),
        "limit": limit,
        "offset": offset,
    }
    if "custom" in requested:
        params["user_id"] = user_id

    parsed = parse_search_text(name or "")
    if mode == "autocomplete":
        if len(parsed.leaf) < AUTOCOMPLETE_MIN_CHARS:
            raise ValueError(
                f"autocomplete needs at least {AUTOCOMPLETE_MIN_CHARS} "
                "characters"
            )
        if offset:
            raise ValueError("autocomplete does not page")
    if not parsed.leaf:
        sql_query = _BROWSE_SQL.format(
            custom_scope=_custom_scope_sql(requested)
        )
        async with get_connection_from_pool() as conn:
            return await conn.run_sync(
                lambda sync_conn: pd.read_sql(
                    text(sql_query), sync_conn, params=params
                )
            )

    params.update(
        {
            "leaf": parsed.leaf,
            "context": parsed.context,
            "k": limit + offset,
            "scale": 1.0,
        }
    )

    async with get_connection_from_pool() as conn:
        normalized = (
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
        ) = normalized

        def _read(sync_conn, sql_query):
            return pd.read_sql(text(sql_query), sync_conn, params=params)

        if mode == "autocomplete":
            params["leaf_query"] = _autocomplete_token_query(leaf_lexemes)
            params["context_query"] = _prefix_tsquery(context_lexemes) or ""
            try:
                return await conn.run_sync(
                    _read,
                    _autocomplete_sql(
                        requested,
                        with_tokens=bool(params["leaf_query"]),
                        with_context=bool(params["context_query"]),
                    ),
                )
            finally:
                await conn.rollback()

        try:
            result = await conn.run_sync(
                _read,
                _search_sql(
                    requested,
                    corrected=False,
                    with_context=bool(parsed.context),
                ),
            )
            if _satisfies(result, parsed):
                return result.drop(columns=["context_hit"])

            # Nothing usable as typed: correct the leaf tokens against the
            # stored ones and search again. Two round trips only on a miss.
            leaf_query = await _corrected_leaf_query(conn, parsed.leaf)
            if leaf_query is None:
                return result.drop(columns=["context_hit"])
            params["leaf_query"] = leaf_query
            params["scale"] = _CORRECTED_SCORE_SCALE
            corrected = await conn.run_sync(
                _read,
                _search_sql(
                    requested,
                    corrected=True,
                    with_context=bool(parsed.context),
                ),
            )
            chosen = corrected if _satisfies(corrected, parsed) else result
            return chosen.drop(columns=["context_hit"])
        finally:
            # Read-only, and the correction's threshold was SET LOCAL: end
            # the transaction so the pooled connection carries nothing over.
            await conn.rollback()


async def fetch_aoi_bbox(source: str, src_id: str) -> list[float]:
    """Return the bbox of one AOI, found by ``(source, src_id)``.

    The bbox is computed at build time, so this function reads it and does
    not derive it. It returns the world bbox if the AOI or its bbox is
    missing, and it logs that result. The map then shows the whole world, and
    the user sees no sign of the cause.
    """
    if source not in VALID_AOI_SOURCES:
        # This function does not accept the source aliases that `search_aois`
        # accepts, so a caller that sends `protectedareas` reaches this line.
        reason = "invalid_source"
    else:
        query = text(
            "SELECT bbox FROM aois "
            "WHERE source = :source AND source_id = :src_id "
            "AND NOT is_deprecated"
        )
        async with get_connection_from_pool() as conn:
            result = await conn.execute(
                query, {"source": source, "src_id": src_id}
            )
            row = result.fetchone()
            if row and row[0]:
                return row[0]

        # A missing row and a null bbox need different repairs, so the log
        # names the cause. A missing row shows a stale id, or a build that
        # skipped the AOI. A null bbox shows a build that wrote the row
        # without a bbox.
        reason = "null_bbox" if row else "no_row"

    logger.warning(
        "AOI bbox lookup fell back to the world bbox.",
        source=source,
        src_id=src_id,
        reason=reason,
    )
    return WORLD_BBOX


def format_id(idx):
    """Remove the GADM version suffix from an id, and return a string.

    A GADM id carries a version suffix, such as the ``_1`` in ``BRA.16_1``.
    The suffix is not part of the hierarchy, and the external analytics API
    rejects it. This function removes ``_1`` through ``_5``.
    """
    idx = str(idx)
    if idx[-2:] in ["_1", "_2", "_3", "_4", "_5"]:
        return idx[:-2]
    return idx


def _response_src_id(source: str, src_id: str) -> Union[int, str]:
    """Keep the ``src_id`` type that geometry responses used before unification.

    ``geometries_kba.sitrecid`` was numeric, so a KBA lookup returned an int.
    ``GeometryResponse.src_id`` is ``int | str`` for that reason. ``aois`` stores
    every id as text, so this cast keeps the response type for KBA clients.
    """
    if source == "kba":
        try:
            return int(src_id)
        except ValueError:
            pass
    return src_id


async def get_geometry_data(
    source: str, src_id: str, user_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Get geometry data by source and source ID.

    A reference source reads the unified ``aois`` table and returns the
    normalized MultiPolygon. ``custom`` reads ``custom_areas`` and returns the
    drawn parts unchanged, so one part gives a ``Polygon`` and two or more
    give a ``GeometryCollection``. The mirrored ``aois`` geometry for a custom
    area is dissolved, so reading it here would change the shape that the
    analytics, thumbnail and mosaic callers already get.

    The reference query does not filter ``is_disputed``. This function finds
    an AOI by id, so it must still return a disputed area. It also does not
    normalize source aliases, so ``protectedareas`` raises.

    This function opens its own session; the caller passes none.

    Args:
        source: Source type (gadm, kba, landmark, wdpa, custom)
        src_id: Source-specific ID
        user_id: User ID (required for custom areas; falls back to request context)

    Returns:
        Dict with name, subtype, source, src_id, and geometry, or None if not
        found. ``geometry`` is None when a custom area holds no parsable part.
        ``subtype`` is ``custom`` for a custom area, and not the
        ``custom-area`` value that the mirror writes.

    Raises:
        ValueError: For invalid source or missing user_id for custom areas
    """

    async with get_session_from_pool() as session:
        if source == "custom":
            user_id = user_id or current_user_id()
            if not user_id:
                raise ValueError("user_id required for custom areas")

            try:
                area_id = UUID(src_id)
            except ValueError:
                raise ValueError(
                    f"Invalid UUID format for custom area ID: {src_id}"
                )

            stmt = select(CustomAreaOrm).filter_by(id=area_id, user_id=user_id)
            result = await session.execute(stmt)
            custom_area = result.scalars().first()

            if not custom_area:
                return None

            # Parse the stored geometries JSONB field
            try:
                geometries = (
                    [
                        json.loads(geom_str)
                        for geom_str in custom_area.geometries
                    ]
                    if custom_area.geometries
                    else []
                )

                if len(geometries) == 0:
                    geometry = None
                elif len(geometries) == 1:
                    geometry = geometries[0]
                else:
                    # Multiple geometries - return as GeometryCollection
                    geometry = {
                        "type": "GeometryCollection",
                        "geometries": geometries,
                    }
            except (json.JSONDecodeError, IndexError):
                geometry = None

            return {
                "name": custom_area.name,
                "subtype": "custom",
                "source": source,
                "src_id": src_id,
                "geometry": geometry,
            }

        # Handle standard geometry sources
        if source not in VALID_AOI_SOURCES:
            raise ValueError(
                f"Invalid source: {source}. Must be one of: "
                f"{', '.join(sorted(VALID_AOI_SOURCES))}"
            )

        # One query serves every reference source, because source_id is text for
        # all of them. The query does not filter is_disputed. Search excludes
        # disputed rows, but this lookup finds an AOI by id and must still
        # return them.
        sql_query = """
            SELECT name, subtype, ST_AsGeoJSON(geometry) AS geometry_json
            FROM aois
            WHERE source = :source
              AND source_id = :src_id
              AND NOT is_deprecated
        """

        q = await session.execute(
            text(sql_query), {"source": source, "src_id": src_id}
        )
        result = q.first()

        if not result:
            return None

        # Parse GeoJSON string
        try:
            geometry = (
                json.loads(result.geometry_json)
                if result.geometry_json
                else None
            )
        except json.JSONDecodeError:
            geometry = None

        return {
            "name": result.name,
            "subtype": result.subtype,
            "source": source,
            "src_id": _response_src_id(source, src_id),
            "geometry": geometry,
        }
