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
| `search_tsv` | weighted tsvector: leaf and every name variant at weight A, context at weight B, and the display name (minus no-data segments) at weight D, so a display name pasted back as a query still matches its row |

`aoi_names` holds one row per name a place is known by: `kind` is `primary`,
`variant` (GADM VARNAME, `|`-separated), `native` (GADM NL_NAME, WDPA
`orig_name` when it differs), `international` (KBA `IntName`) or `code` (a
country's ISO3, so "USA" is the United States). Non-Latin scripts are stored
as they come; `unaccent` passes them through.

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

`search_aois(name, sources, user_id, limit, offset)` keeps its signature and
its result columns. The input string is split on commas: the first segment
is the leaf, the rest are context terms. The leaf is normalized once in SQL
and bound back as a constant, so the exact and prefix lookups are index
ranges; the tsqueries are built inside the statement with the `aoi_search`
configuration, so Python never tokenizes.

One statement finds candidates in three arms and keeps each row's best tier:

| tier | arm | example |
|---|---|---|
| 2 | `aoi_names.name_norm = leaf_norm` | "Lisbon" finds Lisboa through its variant; "USA" finds the United States through its code |
| 1 | `search_tsv @@ leaf tokens` | "Congo" finds every row with the token, both Congos included |
| 1 | `leaf_norm LIKE 'leaf%'` | "Amazon" finds Amazonas |

Within a tier the order is: rows whose context also matches the query's
context (the parent the user typed) first, then the hierarchy prior (country
above state above district, admin units above named sites; the same table
the geocoder's Python scorer uses), then a match on the primary name over
one on a variant, then area, then name. Each arm is sorted the same way and
limited to `limit + offset` rows, which is exact: a row in the final top-N
sits within the top-N of the arm that gave it its tier. The rank is returned
as `similarity_score` in [0, 1] so the geocoder's merge and the replay
fixtures keep working.

The typo correction runs only when the result does not answer the query as
typed: no rows, or a parent was named and no row has it ("Lisbon, Portugal"
must not stop at the US preserves called Lisbon). Each leaf token is
corrected against `aoi_search_tokens` (`token % :tok` at threshold 0.3, set
with `SET LOCAL` for that transaction; best three by similarity then document
frequency) and the token arm is rerun with the corrections. "Bangalor"
becomes "bangalore"; "Lisbon, Portugal" becomes "lisboa AND portugal". This
is the only place trigram matching is used, against short single tokens.

Measured on the corpus after the rewrite: "Paris" 21 ms, "Paris, France"
5 ms, "Congo" 18 ms, "Mumbai" 11 ms, "Bangalor" 11 ms including the
correction, "Botum Sakor" narrowed to WDPA 44 ms, "Puri" 194 ms. The costly
shape is a country name that is also the context of a hundred thousand
rows: "Indonesia" 470 ms and "United States" 510 ms, because the token arm
has to sort every row that carries the token. The country still comes first,
and the previous search took 4.7 s and 2.2 s on the same queries.

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
is unchanged in this phase; the multi-term fan-out and the Python scorer
stay, now fed by a better-ranked candidate list.

One geocoder behaviour did change on purpose: a place given with its parent
("Para, Brazil") no longer triggers the "which one?" nudge. The search now
returns the other countries' same-named places below the parent's match,
where the old search missed them, and a user who named the country has
already answered the question.

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
- The pg_trgm threshold is set with `SET LOCAL` inside the correction's
  transaction only. The per-request `CREATE EXTENSION` / `SET` / `COMMIT`
  preamble is gone.

## Later

- Structured geocoder→search contract (leaf, parent, ISO3, type) so a place
  costs one query instead of up to five.
- `iso3` filter on the API.
- Saved-areas relationship filter.
