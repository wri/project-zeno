# AOI full-text search

How name search over the unified `aois` table works, how to read a result,
where every tuning constant lives, and how to find out why a search did not
return what you expected. The read side is `search_aois` in
`src/shared/aoi_search.py`; the write side (the SQL that fills the columns it
reads) is `src/shared/aoi_search_sql.py`, run by `build-aois` and by the
custom-area mirror. The design rationale and the measurements that drove it
are at the end.

## How search works

### Structures

`aois` carries five search columns, filled on write by `build-aois` and by the
custom-area mirror through the shared SQL fragments:

| column | content |
|---|---|
| `leaf` | the place's own name: GADM `NAME_n`, WDPA `wdpa_name`, KBA `NatName`, LandMark `landmark_name`, the custom area's name |
| `leaf_norm` | `unaccent(lower(btrim(leaf)))`, the key for exact and prefix matching |
| `designation` | the kind of site a source names the row with: WDPA `desig_eng`, LandMark `category`; NULL for GADM, KBA and custom areas |
| `search_tsv` | the full weighted tsvector: leaf and every name variant at weight A, the context at weight B, the display name (minus no-data segments) at weight D, so a display name pasted back as a query still matches its row |
| `name_tsv` | the vector a token query runs against: leaf and variants at weight A, the designation at weight B. No parents and no country: those belong to every child, and "Indonesia" would otherwise match the 85,000 rows beneath it |

The *context* that goes into `search_tsv` is what follows the leaf: GADM
parents and country (consecutive duplicate segments collapsed), WDPA
`desig_eng` + country, KBA `Country`, LandMark `category` + `country`. It is
derived at build time and not stored as text; nothing reads it except the
vector.

`aoi_names` holds one row per alternate spelling of a place, one per
`(aoi_id, name_norm)`: `kind` is `variant` (GADM VARNAME, `|`-separated),
`native` (GADM NL_NAME, WDPA `orig_name` when it differs), `international`
(KBA `IntName`) or `code` (a country's ISO3, so "USA" is the United States).
The leaf itself is not repeated here, and a spelling equal to it is not
stored. Custom areas have no rows. Non-Latin scripts are stored as they come;
`unaccent` passes them through.

`aoi_search_tokens` is the distinct-lexeme table of `name_tsv` over the
reference sources, with the count of names carrying each token (`ndoc`) and
the hierarchy prior of the best-known one (`prominence`), rebuilt at the end
of `build-aois`. It serves only the miss path.

All text goes through one text search configuration, `aoi_search`: a copy of
`simple` with the `unaccent` filter in front. No stemming and no stopword
removal, because place names are proper nouns and "Republic of the Congo"
must keep its "of" and "the".

No-data markers (`NA`, `n.a. (…)`, `?`, `Unknown`) are excluded from every
searchable field. `name` itself, the display string, is unchanged.

### Indexes

| index | serves |
|---|---|
| `idx_aois_leaf_norm` btree, `text_pattern_ops`, partial on live rows, INCLUDE (id, subtype, area_km2, name, source, source_id) | exact leaf match and `LIKE 'prefix%'`; the included columns are the ranking keys, so a prefix arm is an index-only scan. 275 MB on the corpus |
| `idx_aois_name_tsv` GIN, partial on live rows | token queries |
| `idx_aois_search_tsv` GIN, partial on live rows | the typed-parent test, and the fallback for words spread over name and context |
| `idx_aoi_names_name_norm` btree, `text_pattern_ops` | exact and prefix over variants |
| `idx_aoi_search_tokens_trgm` GIN trigram | typo correction |
| `idx_aois_source` (existing) | the source filter; `idx_aois_iso3` also exists but nothing in search reads it |

No trigram index remains on `aois`; the composite-name trigram index and the
ingest scripts' trigram indexes on the `geometries_*` staging tables are
dropped by migration `9c4e1d7f2a60`.

### The query, in tiers

`search_aois(name, sources, user_id, limit, offset, mode)` splits the input on
commas: the first segment is the *leaf*, the rest the *context*. The leaf is
normalized once in SQL and bound back as a constant, so the exact and prefix
lookups are index ranges; the tsqueries are built inside the statement with
the `aoi_search` configuration, so Python never tokenizes.

One statement finds candidates in three arms and keeps each row's best tier:

| tier | arm | example |
|---|---|---|
| 2 (`EXACT_TIER`) | `aois.leaf_norm = leaf_norm` or `aoi_names.name_norm = leaf_norm` | "Lisbon" finds Lisboa through its variant; "USA" finds the United States through its code |
| 1 (`PARTIAL_TIER`) | `name_tsv @@ leaf tokens` | "Congo" finds every place with the token in its name, both Congos included, but not the places inside them |
| 1 (`PARTIAL_TIER`) | `leaf_norm LIKE 'leaf%'` | "Amazon" finds Amazonas |

Each arm is sorted by the keys in [Ranking](#ranking) and limited to
`limit + offset` rows, which is exact: a row in the final top-N sits within
the top-N of the arm that gave it its tier, because every row above it in that
arm also ranks above it in the result.

### The miss path

The miss path runs only when the result does not answer the query as typed:
no rows, or a parent was named and no row has it ("Lisbon, Portugal" must not
stop at the US preserves called Lisbon). Each step is one more round trip.

1. **Fallback.** The token arm is rerun alone over `search_tsv`, for a query
   whose words are spread over the name and its context without a comma
   ("Bristol England", "Paris France").
2. **Token lookup.** One statement looks every word of the leaf up in
   `aoi_search_tokens`: how many names carry it, and the stored tokens
   nearest to it. Nearest means within the trigram threshold (the GIN index
   gate), then by `levenshtein` distance, then by the prominence of the
   best-known place carrying the token, so "paolo" reaches São Paulo's
   "paulo" before a village's "palo" and "brazl" reaches Brazil; at most three
   neighbours, and only within one edit per four letters (so "kashmir", two
   edits from "kashmore" on seven letters, is not corrected). Words under three
   letters pass through unchanged. Skipped for a leaf of more than six
   distinct words, decided from the lexemes before the lookup runs.
3. **Corrected spelling**, when some word has a neighbour other than itself:
   "Banglore" becomes "bangalore"; "Sao Paolo, Brazil" becomes
   "sao AND (paulo OR pablo OR paolo)" and the Brazil context picks São
   Paulo. The one-edit neighbours are tried alone first, then everything the
   lookup kept, so a two-edit neighbour of a prominent place ("bangora", from
   Bamingui-Bangoran) cannot outrank the one-edit correction. Scores are
   scaled by 0.8.
4. **Last word dropped**, then **first word dropped**: "Serengeti NP" finds
   Serengeti, "Ho Chi Minh City" finds Hồ Chí Minh. Scores are scaled by 0.6,
   below a correction, because a small misspelling is a closer reading of the
   input than a missing word. A retry is skipped when the words it keeps
   cannot name a place: one of them is in no name, the one left is in more
   than a thousand names ("republic" from "Czech Republic", "sao" from "Sao
   Paolo") or is under three letters ("np"). Two or more words kept together,
   each in some name, always qualify ("mount AND kenya").

Steps 3 and 4 rerun the token arm over `name_tsv` with a query prepared in
Python, and stop at the first result that answers the query. This is the only
place trigram matching is used, against short single tokens.

Paging interacts with this: an empty page counts as a miss, so an offset past
the end of the as-typed result falls through to the later stages and returns
their rows at that offset. Page two of a corrected result exists because of
this, but so does a page two of typed results followed by corrected rows. The
API's callers page short lists, so it is left as is.

### Autocomplete

`GET /api/aois?name=<text>&mode=autocomplete` completes a keystroke. It needs
at least two characters, takes no offset (the next keystroke replaces the
list) and never corrects a typo. Three arms:

- the normalized leaf starts with the typed text (index-only on the covering
  index), tier 2;
- a stored name variant starts with it ("lisb" reaches Lisboa through
  "Lisbon"), tier 2, as a semi-join so an AOI with several matching variants
  takes one slot of the arm's cut;
- the typed words as tokens with the last one as a prefix ("new y" reaches
  New York), tier 1, used only for several words or a single word of four or
  more letters, because a two-letter prefix expands to thousands of lexemes.

A typed parent ("paris, fr") filters every arm by its own prefix query rather
than ranking. The order is the hierarchy prior first, since a keystroke list
should lead with prominent places, then a leaf prefix over a variant's, then
area.

### Browse

Without a name the search lists every live row in the asked sources, ordered
by `name, source, source_id` on `idx_aois_name_live`. Custom areas stay
owner-scoped by the `user_aois` semi-join in every mode.

## Ranking

### The order within a tier

Rows are sorted by tier first, then within a tier:

1. a context hit (the query named a parent and this row has it), when a
   parent was typed;
2. the hierarchy prior (`HIERARCHY_SCORES`: country above state above
   district, admin units above named sites; the same table the geocoder's
   scorer and the token table use);
3. a match on the leaf over one on a variant ("Lisbon" is Lisboa before a US
   preserve called Lisbon because the prior outranks this key, not despite
   it);
4. the larger area, then name, source, source id.

Every candidate arm sorts by the same keys as the final result, which is what
makes the per-arm cut exact.

### The score is not the sort key

`similarity_score` (the API's `score`) is a summary of the sort keys for
callers that need one number: the API response and the geocoder's multi-term
merge, which deduplicates a row found by several spellings on its best score.
It is `tier / 2 × 0.55 + context_hit × 0.2 + prior × 0.25`, scaled by 0.8 or
0.6 on the miss path; autocomplete uses `tier / 2 × 0.5 + prior × 0.5`. The
weights sum to 1 and keep the sort's precedence, but the score leaves out the
exact-leaf key and the area, so **two rows with equal scores can come back in
either order**. Do not read an ordering problem into that.

### The geocoder's scorer

`pick_aoi` searches a place under several spellings (the user's, a canonical
one, alternatives), merges the frames and picks one row deterministically in
`src/agent/subagents/pick_aoi/scoring.py`. Its score is an accent-insensitive
string comparison against the best-matching term, the hierarchy prior, an
exact-leaf or prefix bonus, and three terms the search reports and the string
comparison cannot see: a bonus for a row that matched a stored name exactly
(`tier`, which covers a variant such as "Lisbon" for Lisboa), a larger bonus
for a row that has the parent the user typed (`context_hit`, worth more than
one hierarchy step because "Victoria, Canada" otherwise picked the Australian
state over the Canadian county), and a penalty for a row the miss path found
(`corrected`). The exact-leaf bonus is judged on the stored `leaf`, not on the
name's first comma segment, because a stored leaf can contain a comma
("Krüger-, Rähden- und Möschensee").

### Knobs

Every tuning constant, where it lives and what it changes. Values are the
current ones; the source is authoritative.

| constant | value | file | changes |
|---|---|---|---|
| `HIERARCHY_SCORES` | country 1.0, state 0.9, district 0.7, custom 0.7, municipality 0.5, locality 0.35, neighbourhood 0.25, KBA/WDPA/LandMark 0.2 | `aoi_search_sql.py` | the prior in the sort, the score, the token table's `prominence`, the geocoder's hierarchy term and nudge floor |
| `_SCORE_TIER_WEIGHT`, `_SCORE_CONTEXT_WEIGHT`, `_SCORE_PRIOR_WEIGHT` | 0.55, 0.2, 0.25 | `aoi_search.py` | the search score only (not the order) |
| `_AUTOCOMPLETE_TIER_WEIGHT`, `_AUTOCOMPLETE_PRIOR_WEIGHT` | 0.5, 0.5 | `aoi_search.py` | the autocomplete score only |
| `_CORRECTED_SCORE_SCALE`, `_PARTIAL_SCORE_SCALE` | 0.8, 0.6 | `aoi_search.py` | how far a corrected / word-dropped result's score sits below an as-typed one |
| `_CORRECTION_MIN_CHARS` | 3 | `aoi_search.py` | words shorter than this are never corrected, and a lone kept word shorter than this cannot carry a word-dropped retry |
| `_CORRECTION_TRGM_THRESHOLD` | 0.3 | `aoi_search.py` | the pg_trgm gate for a stored token to be a neighbour at all |
| `_CORRECTION_NEAREST` | 3 | `aoi_search.py` | neighbours kept per word |
| `_CORRECTION_CHARS_PER_EDIT` | 4 | `aoi_search.py` | edit budget: one edit per this many letters, at least one |
| `_COMMON_TOKEN_NDOC` | 1000 | `aoi_search.py` | a lone kept word in more names than this cannot carry a word-dropped retry |
| `_MAX_MISS_LEXEMES` | 6 | `aoi_search.py` | a leaf of more distinct words gets no miss path |
| `AUTOCOMPLETE_MIN_CHARS`, `_AUTOCOMPLETE_TOKEN_MIN_CHARS` | 2, 4 | `aoi_search.py` | the shortest autocomplete input; the shortest single word that gets the token arm |
| `MAX_SEARCH_NAME_CHARS`, `MAX_SEARCH_OFFSET` | 200, 10,000 | `aoi_search.py` | input caps (422 at the API; the geocoder trims first) |
| `_SIMILARITY_WEIGHT`, `_HIERARCHY_WEIGHT` | 0.5, 0.3 | `scoring.py` | the geocoder scorer's base terms |
| `_EXACT_SEGMENT_BONUS`, `_PREFIX_BONUS` | 0.2, 0.1 | `scoring.py` | term leaf equals the stored leaf; the name starts with the term |
| `_STORED_NAME_BONUS`, `_CONTEXT_MATCH_BONUS`, `_CORRECTED_PENALTY` | 0.1, 0.2, 0.15 | `scoring.py` | the search-reported terms: `tier == EXACT_TIER`, `context_hit`, `corrected` |
| `_NUDGE_PROMINENCE_MARGIN` | country − state = 0.1 | `pick_aoi/tool.py` | how much less prominent a namesake may be and still be offered as a choice; a country is put against a state, a state never against a district |
| `RESULT_LIMIT` | 10 | `pick_aoi/tool.py` | candidates per search term; with exact matches leading the list this was enough for every eval and tools-suite case |
| `_CLOSEST_NAMES` | 3 | `pick_aoi/tool.py` | names offered when a place resolves only to a guess |

## Debugging a search

### Read the result

Every frame `search_aois` returns carries four columns the API does not
expose, and one log line per call says the same things:

- `stage`: which statement the rows came from: `typed`, `fallback`,
  `corrected`, `reduced`, `autocomplete` or `browse`. `typed` with zero rows
  means nothing answered.
- `tier`: 2 for an exact stored-name match (leaf or variant), 1 for a token or
  prefix match.
- `context_hit`: the query named a parent and this row has it.
- `corrected`: the row came from the miss path (`stage` is `corrected` or
  `reduced`).
- `leaf`: the stored leaf, which is what exactness was judged on.

The log line, event `AOI search` from `src.shared.aoi_search`, gives `mode`,
the raw `name`, the parsed `leaf` and `context`, `sources`, `stage`, `tried`
(the miss-path tsqueries in the order they ran), `rows` and `ms`. It is the
first thing to look at for a production case. The geocoder's progress lines
show the candidates it merged, not the stage.

From a shell against a built database:

```python
from src.shared import database
from src.shared.aoi_search import search_aois
await database.initialize_global_pool()
frame = await search_aois("Banglore", None, None)
frame[["src_id", "name", "tier", "stage", "context_hit", "similarity_score"]]
```

### Why a name did not match

Work down this list against the row you expected.

- **The word is in the row's context, not its name.** `name_tsv` holds the
  leaf, its variants and the designation. Parents and the country are only in
  `search_tsv`, which the fallback reads and the typed-parent test uses. A
  country name never matches the places inside it; a query with the parent
  after a comma does.
- **The designation is only stored for WDPA and LandMark.** "Serengeti
  National Park" matches a WDPA row through `desig_eng`; a GADM, KBA or
  custom row has no designation, so a typed kind-of-place word has to be
  dropped by the miss path before those match.
- **The leaf is a no-data marker.** `NA`, `n.a. (…)`, `?` and `Unknown` are
  removed from every searchable field. GADM's `NA` rows have their leaf
  repaired from the hierarchy where the rules reach; the rest are findable
  only by their parents.
- **Hyphenated words.** The parser emits "Île-de-France" as the compound and
  as its parts; queries use the parts only. A stored compound matches through
  its parts, never as one lexeme.
- **The leaf contains a comma.** The query is split at its first comma, so a
  leaf like "Krüger-, Rähden- und Möschensee" cannot be typed exactly; its
  first segment matches as a prefix or token.
- **Custom areas** have no variants, no designation and no typo correction
  (their names stay out of the shared token table), and appear only for their
  owner through `user_aois`.
- **The token table is stale.** `aoi_search_tokens` is rebuilt at the end of
  `build-aois`; a name added since (a custom area, a re-ingest without a
  rebuild) gets no correction and cannot carry a word-dropped retry.
- **The typed parent does not match the stored context, so the as-typed hit
  was discarded.** "Lisbon, PT" or a WDPA row whose context holds an ISO3 code
  (the GADM country row was missing at build) fails the context test, and the
  search falls through to the miss path even though the leaf matched. Check
  `context_hit` on the row and the country segment of its `search_tsv`.
- **Disputed or deprecated.** Excluded from every search mode; resolvable by
  id through `GET /api/geometry/{source}/{src_id}`.
- **The source filter or an alias.** `protectedareas` normalizes to `wdpa`;
  an unknown source is a 422. The geocoder narrows to the inferred type and
  retries every source only when the narrowed result is empty.
- **Equal scores in an unexpected order.** See
  [the score is not the sort key](#the-score-is-not-the-sort-key).
- **The geocoder picked a different row than the search ranked first.** The
  scorer re-ranks across every spelling it tried; the search's rank enters
  only through `tier`, `context_hit` and `corrected`. A guess (`corrected`)
  that still wins is reported as unmatched with the closest names, not
  selected.

### Inspect the data

```sql
-- How the query is normalized and tokenized.
SELECT unaccent(lower(btrim('Île-de-France'))) AS leaf_norm,
       to_tsvector('aoi_search', 'Île-de-France') AS lexemes,
       plainto_tsquery('aoi_search', 'Botum Sakor National Park') AS query;

-- One row's searchable fields.
SELECT source, source_id, name, subtype, leaf, leaf_norm, designation,
       name_tsv, search_tsv, is_disputed, is_deprecated
FROM aois WHERE source = 'gadm' AND source_id = 'FRA.8.3_1';

-- Its stored name variants.
SELECT n.kind, n.name, n.name_norm
FROM aoi_names n JOIN aois a ON a.id = n.aoi_id
WHERE a.source = 'gadm' AND a.source_id = 'PRT.12_1';

-- Does the query reach the row's vectors?
SELECT name_tsv @@ plainto_tsquery('aoi_search', 'botum sakor national park')
         AS name_hit,
       search_tsv @@ plainto_tsquery('aoi_search', 'cambodia') AS context_hit
FROM aois WHERE source = 'wdpa' AND source_id = '555';

-- What the correction sees for a word.
SET pg_trgm.similarity_threshold = 0.3;
SELECT token, ndoc, prominence, levenshtein(token, 'banglore') AS dist
FROM aoi_search_tokens
WHERE token % 'banglore'
ORDER BY dist, prominence DESC, ndoc DESC LIMIT 10;
```

## How the geocoder uses it

The geocoder's contract (`pick_aoi` → `search_aois(name: str)`) is unchanged
in this phase; the multi-term fan-out and the Python scorer stay, fed by a
better-ranked candidate list. Four behaviours changed on purpose, all because
the search now returns every namesake where the old one missed most of them:

- A place given with its parent ("Para, Brazil") no longer triggers the
  "which one?" nudge; a user who named the country has already answered.
- The nudge asks about namesakes, not prefixes: a namesake is a GADM row
  whose stored leaf equals the selection's ("Parisi" is not a Paris), in
  another country (the selection's own country row is not another country:
  São Tomé the district is not put against São Tomé and Príncipe), and of
  comparable prominence: Scotland the state is not put to a vote against the
  US districts called Scotland, while Amazonas in Brazil and Amazonas in Peru
  still are. The options list obeys the same floor. A selected country now
  nudges against a same-named state elsewhere (Georgia, Niger); before, a
  country never nudged because the check keyed on a dotted GADM id.
- The scorer weighs `tier`, `context_hit` and `corrected` as described under
  [Ranking](#the-geocoders-scorer).
- A candidate the search reached only by correcting a spelling or dropping a
  word is a guess. The scorer docks it, so a row that some spelling matched
  as written wins a near-tie; and when a guess still comes first the place is
  reported unmatched with its closest stored names ("Kashmir" is not in the
  corpus; the message offers "Bagh-e-Keshmir"), so the agent asks rather than
  maps it. Eight of the ten guesses the agent path made on the review corpus
  were wrong.

One scorer limit worth knowing, exposed rather than caused by the recall:
"Gunung Leuser National Park" also retrieves the UNESCO reserve whose name
embeds "National Park", and the scorer's exact-leaf bonus prefers it over the
WDPA row whose designation is National Park. Telling those apart needs the
designation as a field, which is the structured geocoder contract planned for
a later phase.

## Operating notes

- **Input caps.** `name` is at most 200 characters and may not contain NUL;
  `offset` is at most 10,000; the miss path runs only for a leaf of at most
  six distinct words. All are enforced in `search_aois` (the API maps the
  error to 422; the geocoder trims the model's string first). Without them a
  long list of real words costs one trigram lookup per word, and a huge
  offset sorts the whole table on disk.
- **Statement shape.** The candidate CTE is `NOT MATERIALIZED`, so the
  planner evaluates the tsquery once and pushes it into each arm's index
  scan instead of building the CTE first. The pg_trgm threshold is set with
  `set_config(…, is_local)` inside the correction's transaction only, and the
  connection is rolled back before it returns to the pool.
- **Deploy order.** The migration adds the search columns empty, and the new
  search reads only them. Run a full `build-aois` right after the migrate Job
  of the deploy that ships this; until it finishes, name search returns
  nothing while browse and id lookups keep working.
- **`build-aois`** populates all search columns and tables and ends with the
  token rebuild and `VACUUM (ANALYZE)` of the four tables: the vacuum sets
  the visibility map the search's index-only scans depend on, which a plain
  `ANALYZE` would not. The reference upsert updates a row only when a column
  differs from the staging value, so a rebuild over unchanged data writes
  nothing. The custom-area write-through keeps `aois` current per request;
  the token table lags until the next build, which only affects the miss
  path for brand-new tokens.
- **Tests.** The test schema comes from `create_all`, so `tests/conftest.py`
  runs the same extension and configuration DDL as the migration. The search
  indexes live in the migration only: the seeded test tables are too small
  for the planner to use them. `tests/api/test_aois.py` covers every tier,
  the miss path, autocomplete and the caps against seeded rows.
- **Replay fixtures.** `tests/tools/test_pick_aoi.py` replays recorded
  `query_aoi_database` frames in CI, so a retrieval change is only visible
  when that suite runs live against a populated database.
  `scripts/record_aoi_pick_aoi_fixtures.py` re-records the fixture from a
  database built by `build-aois`; run it and commit the JSON whenever the
  search's columns or the corpus change, and diff the frames to explain any
  row that moved.

## Why it is built this way

### The problem

The first version of unified search ran one pg_trgm filter, `name % :q` at
threshold 0.2, over a single comma-joined `name` string, and sorted by
`similarity()`. Measured in September 2026 on a local copy of the staging
corpus (849k rows) it failed on both axes:

| query | index candidates | rows kept | time |
|---|---|---|---|
| India | 140,709 | 1,471 | 3.0 s |
| Paris | 93,038 | 31 | 2.0 s |
| Botum Sakor (wdpa only) | 41,666 | 8 | 1.1 s |

The GIN trigram index is lossy. At threshold 0.2 a five-letter query admits
any row that shares two trigrams, and every candidate costs a heap fetch and a
`similarity()` call before the sort. Short, common names, which is what
countries and cities are, pay the most.

The results were also wrong, because trigram similarity is a length-normalized
Jaccard ratio over the whole composite string. "India" scores 0.194 against
"Bangalore Urban, Karnataka, India" (below the threshold) and 0.217 against
"Indiana, United States". "Congo" never matches "Democratic Republic of the
Congo" (0.188). "Para" ranks "Paraná" above "Pará" because accents break
trigrams. Alternate names that every source ships (GADM VARNAME and NL_NAME,
WDPA original names, KBA international names) were never stored, so the
geocoder asked an LLM to guess spellings and ran up to five queries per place.

### Measurements

September 2026, same corpus, warm plans, best of three. As-typed: "Paris"
11 ms, "Paris, France" 13 ms, "Congo" 8 ms, "Mumbai" 8 ms, "Bangalor" 8 ms (a
prefix hit), "Botum Sakor National Park" 9 ms, "Puri" 10 ms. A country name,
the most common real query, is the cheapest shape: "Indonesia" 10 ms, "United
States" 10 ms, "Brazil" 10 ms, because the name vector holds the country's
own name only (before the name vector the token arm sorted every row carrying
the country in its context: 470 and 510 ms; 4.7 and 2.2 s with the previous
search). The miss path costs more and is rarer: "Paris France" 13 ms (the
fallback vector), "Banglore" 47 ms, "Serengeti NP" 46 ms, "Sao Paolo, Brazil"
180 ms and "Ho Chi Minh City" 130 ms (the token lookup, about 30 ms, plus one
or two retries).

Autocomplete: three letters and up run in 15 to 130 ms ("ban" 33, "mumb" 30,
"kaji" 13, "sao p" 105, "高知" 9, "محمية" 34). A two-letter prefix that matches
twenty thousand names costs 90 to 570 ms on the Docker database ("ko" 85, "un"
91, "ba" 567), almost all of it the sort over the index entries.

### Rejected alternatives

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

## Later

- Structured geocoder→search contract (leaf, parent, ISO3, type) so a place
  costs one query instead of up to five.
- `iso3` filter on the API.
- Saved-areas relationship filter.
