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
| `name_tsv` | the vector a token query runs against: leaf and variants at weight A, the designation (WDPA `desig_eng`, LandMark `category`) at weight B. No parents and no country: those belong to every child, and "Indonesia" would otherwise match the 85,000 rows beneath it |

`aoi_names` holds one row per alternate spelling of a place, one per
`(aoi_id, name_norm)`: `kind` is `variant` (GADM VARNAME, `|`-separated),
`native` (GADM NL_NAME, WDPA `orig_name` when it differs), `international`
(KBA `IntName`) or `code` (a country's ISO3, so "USA" is the United States).
The leaf itself is not repeated here: `aois.leaf_norm` is the primary name,
and a spelling equal to it is not stored. Custom areas have no rows.
Non-Latin scripts are stored as they come; `unaccent` passes them through.

`aoi_search_tokens` is the distinct-lexeme table of `name_tsv` over the
reference sources, with the count of names carrying each token and the
hierarchy prior of the best-known one, rebuilt at the end of `build-aois`.
It serves only the miss path below.

All text goes through one text search configuration, `aoi_search`: a copy of
`simple` with the `unaccent` filter in front. No stemming and no stopword
removal, because place names are proper nouns and "Republic of the Congo"
must keep its "of" and "the".

No-data markers (`NA`, `n.a. (…)`, `?`, `Unknown`) are excluded from every
searchable field. `name` itself, the display string, is unchanged.

### Indexes

| index | serves |
|---|---|
| `idx_aois_leaf_norm` btree, `text_pattern_ops`, partial on live rows, INCLUDE (id, subtype, area_km2, name, source, source_id) | exact leaf match and `LIKE 'prefix%'`; the included columns are the ranking keys, so a prefix arm is an index-only scan |
| `idx_aois_name_tsv` GIN, partial on live rows | token queries |
| `idx_aois_search_tsv` GIN, partial on live rows | the typed-parent test, and the fallback for words spread over name and context |
| `idx_aoi_names_name_norm` btree, `text_pattern_ops` | exact and prefix over variants |
| `idx_aoi_search_tokens_trgm` GIN trigram | typo correction |
| `idx_aois_iso3`, `idx_aois_source` (existing) | facets |

The composite-name trigram index and the ingest scripts' trigram indexes on
the `geometries_*` staging tables are dropped by migration `9c4e1d7f2a60`. No
trigram index remains on `aois`.

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
| 2 | `aois.leaf_norm = leaf_norm` or `aoi_names.name_norm = leaf_norm` | "Lisbon" finds Lisboa through its variant; "USA" finds the United States through its code |
| 1 | `name_tsv @@ leaf tokens` | "Congo" finds every place with the token in its name, both Congos included, but not the places inside them |
| 1 | `leaf_norm LIKE 'leaf%'` | "Amazon" finds Amazonas |

Within a tier the order is: rows whose context also matches the query's
context (the parent the user typed) first, then the hierarchy prior (country
above state above district, admin units above named sites; the same table
the geocoder's Python scorer uses), then area, then name. Each arm is
sorted the same way and
limited to `limit + offset` rows, which is exact: a row in the final top-N
sits within the top-N of the arm that gave it its tier. The rank is returned
as `similarity_score` in [0, 1] so the geocoder's merge and the replay
fixtures keep working.

The miss path runs only when the result does not answer the query as
typed: no rows, or a parent was named and no row has it ("Lisbon, Portugal"
must not stop at the US preserves called Lisbon). First the token arm is
rerun alone over `search_tsv`, for a query whose words are spread over the
name and its context without a comma ("Bristol England", "Paris France").
Then one statement looks every word of the leaf up in `aoi_search_tokens`: how many names carry it, and the
stored tokens nearest to it (`token % :tok` at threshold 0.3, set with `SET
LOCAL` for that transaction, then by `levenshtein` distance, then the
prominence of the best-known place carrying the token, so "paolo" reaches
São Paulo's "paulo" before a village's "palo" and "brazl" reaches Brazil;
at most three, and only within `greatest(1, length / 4)` edits so "kashmir"
is not "kashmore"). Words under three letters pass through. Then
the token arm is rerun over `name_tsv`, at most three times, stopping at
the first result that answers the query:

1. **Corrected spelling**, when some word has a neighbour other than itself:
   "Bangalor" becomes "bangalore"; "Sao Paolo, Brazil" becomes
   "sao AND (paulo OR paola OR paolo)" and the Brazil context picks São
   Paulo. Scores are scaled by 0.8.
2. **Last word dropped**, then **first word dropped**: "Serengeti NP" finds
   Serengeti, "Ho Chi Minh City" finds Hồ Chí Minh. Scores are scaled by
   0.6, below a correction, because a small misspelling is a closer reading
   of the input than a missing word. A retry is skipped when the words it
   keeps cannot name a place: none is in the corpus, the one left is in
   more than a thousand names ("republic" from "Czech Republic", "sao" from
   "Sao Paolo") or is under three letters ("np"). Two or more words kept
   together always qualify ("mount AND kenya").

This is the only place trigram matching is used, against short single
tokens. The lookup costs about 30 ms; a retry costs one token-arm query.

Measured on the corpus (849k rows, warm plans, best of three): "Paris"
11 ms, "Paris, France" 13 ms, "Congo" 8 ms, "Mumbai" 8 ms, "Bangalor" 8 ms
including the correction, "Botum Sakor National Park" 9 ms, "Puri" 10 ms.
A country name, the most common real query, is now the cheapest shape:
"Indonesia" 10 ms, "United States" 10 ms, "Brazil" 10 ms, because the name
vector holds the country's own name only. Before the name vector the token
arm sorted every row carrying the country in its context: 470 ms and 510 ms
for the first two, and 4.7 s and 2.2 s with the previous search. The miss
path costs more per query and is rarer: "Paris France" 13 ms (the fallback
vector), "Serengeti NP" 46 ms, "Sao Paolo, Brazil" 180 ms and "Ho Chi Minh
City" 130 ms (the token lookup plus one or two retries).

### Autocomplete

`GET /api/aois?name=<text>&mode=autocomplete` completes a keystroke. It
needs at least two characters, takes no offset (the next keystroke replaces
the list) and never corrects a typo. Three arms, each ranked by the hierarchy
prior first so the list leads with prominent places, then a leaf prefix over
a variant's, then area:

- the normalized leaf starts with the typed text (index-only on the covering
  index);
- a stored name variant starts with it ("lisb" reaches Lisboa through
  "Lisbon");
- the typed words as tokens with the last one as a prefix ("new y" reaches
  New York), used only for several words or a single word of four or more
  letters, because a two-letter prefix expands to thousands of lexemes.

A typed parent ("paris, fr") filters every arm by its own prefix query.

Measured on the corpus: three letters and up run in 15 to 130 ms ("ban" 33,
"mumb" 30, "kaji" 13, "sao p" 105, "高知" 9, "محمية" 34). A two-letter prefix
that matches twenty thousand names costs 90 to 570 ms on the Docker database
("ko" 85, "un" 91, "ba" 567), almost all of it the sort over the index
entries.

### What did not change

Browse mode (no name) still orders by `name, source, source_id` on
`idx_aois_name_live`. Custom areas stay owner-scoped by the `user_aois`
semi-join. The geocoder's contract (`pick_aoi` → `search_aois(name: str)`)
is unchanged in this phase; the multi-term fan-out and the Python scorer
stay, now fed by a better-ranked candidate list.

Three geocoder behaviours did change on purpose, all because the search now
returns every namesake where the old one missed most of them:

- A place given with its parent ("Para, Brazil") no longer triggers the
  "which one?" nudge; a user who named the country has already answered.
- The nudge only offers namesakes of comparable prominence: Scotland the
  state is not put to a vote against the US districts called Scotland, while
  Amazonas in Brazil and Amazonas in Peru still are. (A selected country never
  nudged, before or after: the check keys on a dotted GADM id.)
- The deterministic scorer adds a fifth of the search's own rank to its
  name comparison. The rank knows what the string comparison cannot: that a
  row matched a stored name exactly and that the typed parent matched. "Las
  Palmas, Spain" reads almost the same against the Canarian and the
  Panamanian Las Palmas; the rank picks Spain.

The candidate limit stays at 10 per term. With the new ranking the exact
matches lead the list, so 10 was enough for every eval and tools-suite case,
and a larger list would only lengthen the nudge's options for common names.

One scorer limit worth knowing, exposed rather than caused by the recall:
"Gunung Leuser National Park" now also retrieves the UNESCO reserve whose
name embeds "National Park", and the scorer's exact-leaf bonus prefers it
over the WDPA row whose designation is National Park. Telling those apart
needs the designation as a field, which is the structured geocoder contract
planned for a later phase.

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

- **Input caps.** `name` is at most 200 characters and may not contain NUL;
  `offset` is at most 10,000; the miss path runs only for a leaf of at most
  six distinct words. All are enforced in `search_aois` (the API maps the
  error to 422; the geocoder trims the model's string first). Without them a
  long list of real words costs one trigram lookup per word, and a huge
  offset sorts the whole table on disk.
- **Token table and privacy.** `aoi_search_tokens` is shared by every user,
  so custom-area names stay out of it; a custom area is still found by the
  exact and token tiers, it just gets no typo correction or word dropping.
- **Statement shape.** The candidate CTE is `NOT MATERIALIZED`, so the
  planner evaluates the tsquery once and pushes it into each arm's index
  scan instead of building the CTE first.

- **Deploy order.** The migration adds the search columns empty, and the new
  search reads only them. Run a full `build-aois` right after the migrate Job
  of the deploy that ships this; until it finishes, name search returns
  nothing while browse and id lookups keep working. The old trigram index is
  dropped by a second migration in the same deploy, because nothing reads it
  once the new code is live.

- `build-aois` populates all search columns and tables and ends with the
  token rebuild and `VACUUM (ANALYZE)` of the four tables: the vacuum sets
  the visibility map the search's index-only scans depend on, which a plain
  `ANALYZE` would not. The reference upsert updates a row only when a column
  differs from the staging value, so a rebuild over unchanged data writes
  nothing, keeps the heap compact and reports the rows it would have
  rewritten as unchanged. The custom-area write-through keeps `aois` current
  per request; the token table lags until the next build, which only affects
  the miss path for brand-new tokens.
- The test schema comes from `create_all`, so `tests/conftest.py` runs the
  same extension and configuration DDL as the migration, and the search
  indexes are declared on the ORM models so tests see the real plans.
- `tests/tools/test_pick_aoi.py` replays recorded `query_aoi_database` frames
  in CI, so a retrieval change is only visible when that suite runs live
  against a populated database. `scripts/record_aoi_pick_aoi_fixtures.py`
  re-records the fixture from a database built by `build-aois`; run it and
  commit the JSON whenever the search or the corpus changes.
- The pg_trgm threshold is set with `SET LOCAL` inside the correction's
  transaction only. The per-request `CREATE EXTENSION` / `SET` / `COMMIT`
  preamble is gone.

## Later

- Structured geocoder→search contract (leaf, parent, ISO3, type) so a place
  costs one query instead of up to five.
- `iso3` filter on the API.
- Saved-areas relationship filter.
