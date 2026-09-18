# AOI full-text search

How name search over the unified `aois` table works after the search overhaul,
and why it is built this way. Companion to `docs/aoi-architecture/`.

## Why the overhaul

The first version of unified search ran one pg_trgm filter, `name % :q` at
threshold 0.2, over a single comma-joined `name` string, and sorted by
`similarity()`. Measured on the production corpus (849k rows) it fails on both
axes:

| query | index candidates | rows kept | time |
|---|---|---|---|
| India | 140,709 | 1,471 | 3.0 s |
| Paris | 93,038 | 31 | 2.0 s |
| Botum Sakor (wdpa only) | 41,666 | 8 | 1.1 s |

The GIN trigram index is lossy. At threshold 0.2 a five-letter query admits
any row that shares two trigrams, and every candidate costs a heap fetch and a
`similarity()` call before the sort. Short, common names, which is what
countries and cities are, pay the most.

The results are also wrong, because trigram similarity is a length-normalized
Jaccard ratio over the whole composite string. "India" scores 0.194 against
"Bangalore Urban, Karnataka, India" (below the threshold) and 0.217 against
"Indiana, United States". "Congo" never matches "Democratic Republic of the
Congo" (0.188). "Para" ranks "Paraná" above "Pará" because accents break
trigrams. Alternate names that every source ships (GADM VARNAME and NL_NAME,
WDPA original names, KBA international names) were never stored, so the
geocoder asks an LLM to guess spellings and runs up to five queries per place.

## How search works now

### Structures

`aois` carries four extra columns, filled on write by `build-aois` and by the
custom-area mirror through shared SQL in `src/shared/aoi_search_sql.py`:

| column | content |
|---|---|
| `leaf` | the place's own name: GADM `NAME_n`, WDPA `wdpa_name`, KBA `NatName`, LandMark `landmark_name`, the custom area's name |
| `leaf_norm` | `unaccent(lower(btrim(leaf)))` — the key for exact and prefix matching |
| `context` | what follows the leaf: GADM parents and country (consecutive duplicate segments collapsed), WDPA `desig_eng` + country, KBA `Country`, LandMark `category` + `country` |
| `search_tsv` | weighted tsvector: leaf and every name variant at weight A, context at weight B |

`aoi_names` holds one row per name a place is known by: `kind` is `primary`,
`variant` (GADM VARNAME, `|`-separated), `native` (GADM NL_NAME, WDPA
`orig_name` when it differs) or `international` (KBA `IntName`). Non-Latin
scripts are stored as they come; `unaccent` passes them through.

`aoi_search_tokens` is the distinct-lexeme table of `search_tsv` (`ts_stat`,
~515k tokens), rebuilt at the end of `build-aois`. It exists only for typo
correction.

All text goes through one text search configuration, `aoi_search`: a copy of
`simple` with the `unaccent` filter in front. No stemming and no stopword
removal, because place names are proper nouns and "Republic of the Congo"
must keep its "of" and "the".

No-data markers (`NA`, `n.a. (…)`, `?`, `Unknown`) are excluded from every
searchable field. `name` itself, the display string, is unchanged.

### Indexes

| index | serves |
|---|---|
| `idx_aois_leaf_norm` btree, `text_pattern_ops`, partial on live rows | exact leaf match and `LIKE 'prefix%'` |
| `idx_aois_search_tsv` GIN, partial on live rows | token queries |
| `idx_aoi_names_name_norm` btree, `text_pattern_ops` | exact and prefix over variants |
| `idx_aoi_search_tokens_trgm` GIN trigram | typo correction |
| `idx_aois_iso3`, `idx_aois_source` (existing) | facets |

The composite-name trigram index is dropped once nothing reads it. No trigram
index remains on `aois`.

### The query, in tiers

`search_aois(name, sources, user_id, limit, offset, mode)` keeps its signature
and its result columns. The input string is split on commas: the first segment
is the leaf, the rest are context terms. Both are turned into tsqueries with
the `aoi_search` configuration inside SQL, so Python never tokenizes.

One statement finds candidates in three arms and keeps each row's best tier:

| tier | arm | example |
|---|---|---|
| 3 | `aoi_names.name_norm = leaf_norm` | "Lisboa" finds the row whose primary name is Lisboa; "Bombay" finds Mumbai through its variant |
| 2 | `search_tsv @@ (leaf tokens AND context tokens)` | "Paris, France" requires both "paris" and "france" |
| 1 | `search_tsv @@ leaf tokens` | "Congo" finds every row with the token, both Congos included |

Ranking is `tier`, then exact-leaf, then a hierarchy prior (country above
state above district, admin units above named sites; the same table the
geocoder's Python scorer uses), then area, then name. The rank is returned as
`similarity_score` in [0, 1] so the geocoder's merge and the replay fixtures
keep working.

Only when that statement returns nothing does the fuzzy fallback run: each leaf
token is corrected against `aoi_search_tokens` (`token % :tok`, threshold 0.3,
best three by similarity then document frequency), and the token query is
rerun with the corrections. "Bangalor" becomes "bangalore"; "Lisbon, Portugal"
becomes "lisboa AND portugal". This is the only place trigram matching is used,
against short single tokens, and it costs 30 to 70 ms when it runs.

Measured on the same corpus: "Paris, France" 44 ms, "Congo" 3 ms, "Mumbai"
3 ms, "Bangalor" 60 ms including the correction, "Botum Sakor" narrowed to
WDPA under 1 ms.

### Autocomplete

`GET /api/aois?name=<text>&mode=autocomplete` needs at least two characters,
takes no offset and never falls back to fuzzy. A single token matches
`leaf_norm LIKE 'prefix%'` and the same over `aoi_names`. Several tokens go to
the tsvector with `:*` on the last one, so "bangalore ur" matches "Bangalore
Urban". Results are ordered by exact-prefix on the leaf, hierarchy prior and
area. Prefix lookups run in under 1 ms on rare prefixes and ~20 ms on a
three-letter prefix that matches thousands of rows.

### What did not change

Browse mode (no name) still orders by `name, source, source_id` on
`idx_aois_name_live`. Custom areas stay owner-scoped by the `user_aois`
semi-join. The geocoder's contract (`pick_aoi` → `search_aois(name: str)`)
is unchanged in this phase; the multi-term fan-out and the Python scorer stay,
now fed by a better-ranked candidate list of 25 instead of 10.

## Rejected alternatives

- **Repair in place** with `word_similarity` over the composite name: 1.2 to
  3 s per query on the real corpus, same lossy-index problem.
- **GiST trigram KNN** as the fuzzy tier: 500 to 650 ms per query, and the
  planner preferred it over the btree for plain equality.
- **Fuzzy over whole leaf names** with GIN at threshold 0.3: 40 to 540 ms, and
  a country or source hint does not help because the planner applies it after
  the trigram recheck. Token-level correction is cheaper and also fixes a typo
  inside a multi-word name.
- **Phonetic matching**: English-centric; the cases people mean by "sounds
  like" (Bombay/Mumbai, Zaire/DRC) are alternate names, which the names table
  covers.
- **External search engine**: new infrastructure and a sync problem for a
  corpus Postgres handles in milliseconds once modelled correctly.

## Operating notes

- `build-aois` populates all search columns and tables and ends with the
  token rebuild and `ANALYZE`. The custom-area write-through keeps `aois` and
  `aoi_names` current per request; the token table lags until the next build,
  which only affects typo correction for brand-new tokens.
- The test schema comes from `create_all`, so `tests/conftest.py` runs the
  same extension and configuration DDL as the migration, and the search
  indexes are declared on the ORM models so tests see the real plans.
- `tests/tools/test_pick_aoi.py` replays recorded `query_aoi_database` frames
  in CI, so a retrieval change is only visible when that suite runs live
  against a populated database. Any change in its live results is documented
  in the PR with the query and the before/after candidates.
- The pg_trgm threshold is set once on the engine (`server_settings`), not per
  request. The per-request `CREATE EXTENSION` / `SET` / `COMMIT` preamble is
  gone.

## Later

- Structured geocoder→search contract (leaf, parent, ISO3, type) so a place
  costs one query instead of up to five.
- `iso3` filter on the API.
- Saved-areas relationship filter.
