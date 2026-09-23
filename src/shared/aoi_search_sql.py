"""SQL fragments and DDL for AOI name search.

Search reads three structures that every write path must fill the same way:
the normalized leaf name and the two weighted tsvectors on ``aois``, the name
variants in ``aoi_names``, and the distinct-token table ``aoi_search_tokens``
used when a query misses. ``build-aois`` (:mod:`src.api.cli`), the custom-area mirror
(:mod:`src.api.services.aoi_sync`), the migration and the test fixture all
import these fragments, so no two writers can normalize differently.

The module has no dependencies beyond the standard library, because the
alembic migration imports it.
"""

# Text search configuration used for every tsvector and tsquery. A copy of
# ``simple`` with the ``unaccent`` filter in front: no stemming and no stopword
# removal, because place names are proper nouns ("Republic of the Congo" keeps
# "of" and "the"). Non-Latin scripts pass through unaccent unchanged.
TS_CONFIG = "aoi_search"

# Idempotent, so the migration, the test fixture and a local reset can all run
# it. Postgres has no CREATE TEXT SEARCH CONFIGURATION IF NOT EXISTS. The
# extension and the configuration are pinned to ``public`` so that neither the
# dictionary lookup nor the tsvector calls depend on the caller's search_path.
SEARCH_DDL = [
    "CREATE EXTENSION IF NOT EXISTS unaccent WITH SCHEMA public",
    # levenshtein(), for ranking typo corrections.
    "CREATE EXTENSION IF NOT EXISTS fuzzystrmatch WITH SCHEMA public",
    f"""
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_ts_config c
            JOIN pg_namespace n ON n.oid = c.cfgnamespace
            WHERE c.cfgname = '{TS_CONFIG}' AND n.nspname = 'public'
        ) THEN
            CREATE TEXT SEARCH CONFIGURATION public.{TS_CONFIG} (COPY = simple);
            ALTER TEXT SEARCH CONFIGURATION public.{TS_CONFIG}
                ALTER MAPPING FOR asciiword, asciihword, hword_asciipart,
                    word, hword, hword_part, numword, numhword, hword_numpart
                WITH public.unaccent, simple;
        END IF;
    END
    $$
    """,
]


# Preference by subtype: broader admin units beat narrower ones, and admin
# units beat named sites (KBA/WDPA/Landmark), so a bare "Lisbon" resolves to
# the Portuguese district rather than a small "Lisbon Forest Preserve". Search
# ranks with it in SQL, the token table stores each token's best value so a
# typo corrects to the best-known place, and the geocoder's scorer re-uses it
# in Python. The weights are tuning constants, hand-authored.
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


def hierarchy_prior_sql(subtype_expr: str) -> str:
    """``HIERARCHY_SCORES`` as a SQL CASE over *subtype_expr*, in [0, 1]."""
    arms = " ".join(
        f"WHEN '{subtype}' THEN {score}"
        for subtype, score in HIERARCHY_SCORES.items()
    )
    return f"(CASE {subtype_expr} {arms} ELSE 0.0 END)"


def norm_sql(expr: str) -> str:
    """Normalize a name for exact and prefix comparison.

    Lowercase, accents stripped, outer whitespace removed. The same expression
    normalizes the stored names and the query, so "Pará" and "para" compare
    equal. ``unaccent`` is not IMMUTABLE, so the result is stored on write and
    never used in an index expression.
    """
    return f"unaccent(lower(btrim({expr})))"


def clean_name_sql(expr: str) -> str:
    """Return *expr* trimmed, or NULL when it is a no-data marker.

    The sources use several markers for a missing name: GADM writes ``NA`` and
    ``n.a. ( 2050)``, two GADM ids are ``?``, and LandMark writes ``Unknown``.
    A marker must not become a searchable name, so every writer passes the raw
    name through this fragment first.
    """
    trimmed = f"btrim({expr})"
    return (
        f"CASE WHEN {trimmed} = '' "
        f"OR {trimmed} IN ('NA', '?', 'Unknown', 'unknown') "
        f"OR {trimmed} ~* '^n\\.a\\.' "
        f"THEN NULL ELSE {trimmed} END"
    )


def strip_sentinel_segments_sql(expr: str) -> str:
    """Return the display name *expr* without its no-data segments.

    "Bristol, NA, England, United Kingdom" becomes "Bristol, England, United
    Kingdom", so the marker is not a token of the display name either.
    """
    return (
        f"regexp_replace(COALESCE({expr}, ''), "
        "'(^|, )(NA|\\?|Unknown|unknown|n\\.a\\.( \\([^)]*\\))?)(?=,|$)', "
        "'', 'g')"
    )


def name_tsv_sql(
    leaf_expr: str, variants_expr: str, designation_expr: str
) -> str:
    """The tsvector a token query runs against: the place's own names at A
    and its designation at B.

    *leaf_expr* and *variants_expr* are the names the place is known by;
    *designation_expr* is the kind of site a source names it with ("National
    Park", "Indigenous territory"), so "Botum Sakor National Park" still
    matches. Parents and country are not in it: they belong to every child,
    and a country name would otherwise match every row beneath it.
    """
    return (
        f"setweight(to_tsvector('{TS_CONFIG}', COALESCE({leaf_expr}, '')), 'A') "
        f"|| setweight(to_tsvector('{TS_CONFIG}', COALESCE({variants_expr}, '')), 'A') "
        f"|| setweight(to_tsvector('{TS_CONFIG}', COALESCE({designation_expr}, '')), 'B')"
    )


def tsv_sql(
    leaf_expr: str, variants_expr: str, context_expr: str, name_expr: str
) -> str:
    """The full tsvector: the place's own names at A, its context at B, its
    display name at D. It answers whether a typed parent matches, and it is
    the fallback for a query whose words are spread over name and context
    ("Bristol England").

    *leaf_expr* and *variants_expr* are the names the place is known by, and
    both carry weight A so a token search finds a place under any of them.
    *context_expr* holds the parents, designation or country, at weight B.
    *name_expr* is the display name at weight D: it repeats the tokens above
    and adds the source's own extras (an ISO3 code, an original-language
    designation), so a display name pasted back as a query, which is what an
    ``aoi_choice`` nudge does, matches the row it came from. Each expression
    may be NULL.
    """
    return (
        f"setweight(to_tsvector('{TS_CONFIG}', COALESCE({leaf_expr}, '')), 'A') "
        f"|| setweight(to_tsvector('{TS_CONFIG}', COALESCE({variants_expr}, '')), 'A') "
        f"|| setweight(to_tsvector('{TS_CONFIG}', COALESCE({context_expr}, '')), 'B') "
        f"|| setweight(to_tsvector('{TS_CONFIG}', "
        f"{strip_sentinel_segments_sql(name_expr)}), 'D')"
    )


# Rebuild the distinct-token table from the reference rows' name vectors:
# what a query's words are matched and corrected against, with the count of
# names carrying each token and the hierarchy prior of the best-known one.
# It reads every vector once, so this runs at the end of ``build-aois``.
# Custom areas stay out: the table is shared by every user, and a private
# area name must not steer another user's typo correction. A custom area is
# still found by the exact and token tiers; it just gets no correction.
TOKENS_REBUILD_SQL = [
    "TRUNCATE aoi_search_tokens",
    f"""
    INSERT INTO aoi_search_tokens (token, ndoc, prominence)
    SELECT t.lexeme, count(*), max({hierarchy_prior_sql("a.subtype")})
    FROM aois a, unnest(a.name_tsv) AS t(lexeme, positions, weights)
    WHERE NOT a.is_disputed AND NOT a.is_deprecated
      AND a.source <> 'custom' AND a.name_tsv IS NOT NULL
    GROUP BY t.lexeme
    """,
]
