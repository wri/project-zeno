# ADR-001: AOI Selection Pipeline Overhaul

**Status:** Accepted
**Date:** 2026-03-23
**Authors:** Adam Pain, Claude

## Context

The `pick_aoi` tool is the entry point for all geospatial analysis in Project Zeno. Every user query that involves a geographic area flows through this tool to resolve a place name into a structured AOI (Area of Interest) with geometry data.

### Problems observed

**1. Structural: scattered source configuration**

AOI source metadata was duplicated across three files:

- `geocoding_helpers.py` — `SOURCE_ID_MAPPING` (table + id_column per source), `SUBREGION_TO_SUBTYPE_MAPPING`, `format_id()` suffix stripping
- `analytics_handler.py` — `_get_aoi_type()` 6-way if/elif mapping subtypes to API payloads
- `pick_aoi.py` — `SUBREGION_LIMIT` / `SUBREGION_LIMIT_KBA` constants, inline `int(src_id)` coercion for KBA

Adding a new AOI source (e.g., a watershed table) required coordinated changes in all three files. Each file had its own way of identifying a source — string comparisons like `if source == "kba"` — with no shared type system.

**2. Performance: LLM call for every disambiguation**

`select_best_aoi()` sent every set of trigram-matched candidates to Gemini Flash as a CSV string and asked the LLM to pick the best one using structured output. This added 500ms–2s per place name, consumed tokens, and introduced non-determinism. The LLM was solving a ranking problem that could be handled deterministically.

**3. Recall: single-term trigram search**

`query_aoi_database()` searched with a single term using PostgreSQL `pg_trgm` similarity. This failed for:
- Name equivalences: "Ivory Coast" vs "Côte d'Ivoire" (0% trigram overlap)
- Transliterations: "Москва" vs "Moscow"
- Abbreviations: "DRC" vs "Democratic Republic of the Congo"
- Accented variants: "Sao Paulo" vs "São Paulo" (lower similarity score)

**4. Missing capability: geographic concepts**

Users frequently queried natural features, biomes, and regions ("the Cerrado", "the Congo Basin", "BRICS nations") that don't exist as rows in any geometry table. These queries returned empty results or resolved to an unrelated partial match.

A secondary failure mode existed within this problem: terms like "the Colombian coastline" had enough lexical overlap with "Colombia" (shared trigrams: `col`, `olo`, `lom`, `omb`, `mbi`, `bia`) to score above the 0.3 concept-expansion threshold, so the concept path was silently suppressed and the country was returned instead of the coastal departments. This is a **false positive DB match** — the string matches a row but the semantic intent doesn't.

**5. Accent confusion in scoring**

The deterministic scorer's prefix match was accent-sensitive: `"pará, brazil".startswith("para, brazil")` returned `False`. This caused "Para, Brazil" to match "Paraná, Brazil" (6 chars) instead of "Pará, Brazil" (4 chars) because trigram scores were nearly identical and the prefix bonus couldn't distinguish them.

**6. Low test coverage**

4 integration tests, no unit tests for the scorer or data model, no coverage of edge cases like accented names, cross-source ambiguity, or error handling.

### Production failure evidence

Analysis of user traces revealed 13 distinct failure patterns:

| Mode | Example | Root cause |
|---|---|---|
| `no_aoi_resolved` | "Protected Areas for Tanzania" | Simple country lookup returned empty |
| `no_aoi_resolved` | "Angeles National Forest" | WDPA search failed |
| `wrong_place` | "North Kalimantan" | English name not in DB (stored as "Kalimantan Utara") |
| `wrong_place` | "Hungarian forest" | Adjective form not searchable |
| `biome_resolved_to_admin` | "miombo woodland" | No biome table, concept not handled |
| `multi_area_resolved_to_single` | "coastline of Brazil" | Resolved to country, not coastal states |
| `wrong_resolution_level` | "Lahti city Finland" | Country matched instead of municipality |
| `watershed_resolved_to_admin` | "Congo Basin", "Jubba River" | Watershed/basin concepts not in DB |

## Decision

### 1. AOI Source Registry (`src/shared/aoi/`)

Introduce a registry pattern where each AOI source self-describes its configuration:

```python
@dataclass(frozen=True)
class AOISourceConfig:
    source_type: AOISourceType     # enum: gadm, kba, wdpa, landmark, custom
    table: str                     # "geometries_gadm"
    id_column: str                 # "gadm_id"
    subregion_limit: int           # 50
    analytics_mapping: AnalyticsAPIMapping  # {type: "admin", provider: "gadm", version: "4.1"}
    coerce_id: Callable            # str (or int for KBA)
    geometry_is_postgis: bool      # True (False for custom JSONB)
```

All source-specific lookups (table existence checks, UNION query building, subregion queries, analytics API payloads, ID coercion, subregion limits) derive from this single registry. Existing exports (`SOURCE_ID_MAPPING`, `SUBREGION_TO_SUBTYPE_MAPPING`) are preserved as computed values for backward compatibility.

**Rationale:** One registration call to add a new source, zero changes to consumer code. Type-safe enums prevent string typos. Frozen dataclasses enforce immutability.

### 2. Deterministic Scorer (replaces LLM)

Replace `select_best_aoi()` LLM call with a pure-Python composite scoring function:

```
score = similarity × 0.5          # PostGIS trigram (strongest signal)
      + hierarchy  × 0.3          # country=1.0 > state=0.8 > district=0.6 > ...
      + segment_match × 0.2       # accent-stripped first-segment exact match
        or prefix × 0.1           # accent-stripped prefix match (weaker)
```

The accent-aware segment matching uses `unicodedata.normalize("NFKD")` to strip diacritics before comparison:
- `_first_segment("Pará, Brazil")` → `"para"` == `_first_segment("Para, Brazil")` → exact bonus
- `_first_segment("Paraná, Brazil")` → `"parana"` ≠ `"para"` → no bonus

**Rationale:** Eliminates 500ms–2s LLM latency, removes non-determinism, and the accent-stripping solves the Pará/Paraná confusion that the old prefix check couldn't handle. The hierarchy tiebreaker (country > state > district) encodes the same preference the LLM prompt instructed.

**Trade-off:** The LLM had world knowledge for contextual disambiguation (e.g., "deforestation in Para" → the LLM knew Para, Brazil is the deforestation hotspot, not Para, Suriname). The scorer handles this via the existing `check_multiple_matches` flow which asks the user when same-named places exist across countries. This is arguably better UX than the LLM silently guessing.

### 3. Flash Name Normalizer (pre-search) with concept detection

Add a Gemini Flash Lite call **before** the database query to normalize raw place names and classify geographic concepts in a single call:

```python
class NormalizedPlaceName(BaseModel):
    primary: str             # "Côte d'Ivoire"
    alternatives: list[str]  # ["Ivory Coast"]
    iso_country_code: str | None  # "CIV"
    is_concept: bool         # True for biomes, coastlines, basins, informal regions
```

All terms (primary + alternatives) are searched in parallel via a single UNION query with `DISTINCT ON (source, src_id)` deduplication.

The `is_concept` field solves the false-positive DB match problem: when the normalizer returns `True`, Phase 2 (DB search) is **skipped entirely** and concept expansion fires unconditionally — regardless of trigram similarity scores. This is a semantic judgment, not a syntactic threshold.

```
"the Colombian coastline"
  → normalizer: is_concept=True          ← Flash knows coastlines aren't GADM rows
  → DB search skipped
  → concept expansion: Atlántico, Magdalena, Chocó departments
  → correct result

Previously (trigram-only trigger):
  → DB search: "Colombia" scores 0.35 > 0.3 threshold
  → concept expansion suppressed
  → wrong result: Colombia country
```

**Rationale:** Flash Lite adds ~150ms but fixes two classes of recall failures simultaneously: name equivalences/transliterations (via `primary`/`alternatives`) and false-positive DB matches for concepts (via `is_concept`). No extra LLM call — the concept classification is part of the same structured output. Timeout (2s) with passthrough fallback (`is_concept=False`) ensures graceful degradation.

**Trade-off:** Adds a runtime dependency on Gemini Flash Lite. If the API is unavailable, the normalizer falls back to raw input with `is_concept=False` — identical to old behavior (concept expansion still fires via the trigram fallback for terms with no DB match at all).

### 4. Geographic Concept Expansion (fallback)

When `norm.is_concept=True` **or** the database returns 0 results (or best similarity < 0.3), trigger a Flash Lite call to expand the concept into concrete admin units:

```python
class ConceptExpansion(BaseModel):
    is_concept: bool
    places: list[str]           # ["Goiás", "Mato Grosso do Sul", ...]
    admin_level: str            # "state"
    coverage_note: str          # "these 11 states overlap ~85% with the Cerrado"
    source_hint: str | None     # "wdpa" if concept implies protected areas
```

Results are cached 24h via `cachetools.TTLCache(maxsize=256)`.

**Rationale:** Enables an entirely new class of queries (biomes, basins, regions, geopolitical groupings). The `is_concept` flag from the normalizer means truly concept-like terms (coastlines, river basins, informal regions) trigger expansion even when they partially match real DB entries. The coverage note flows to the user so they know the approximation quality.

**Trade-off:** The spatial approximation is imperfect — "the Cerrado" mapped to Brazilian states includes non-Cerrado portions of some states. Explicitly communicated via the coverage note. The `is_concept` normalizer flag may occasionally misclassify edge cases (e.g., a real place name that sounds like a concept). Mitigated by the trigram fallback — if Flash incorrectly sets `is_concept=True` for a real named place, concept expansion will re-query the DB and may still find it.

## Consequences

### Positive

- **Latency reduction:** ~600–2200ms → ~200–400ms per `pick_aoi` call (LLM disambiguation eliminated, Flash Lite normalization is cheaper)
- **Recall improvement:** "Ivory Coast", "DRC", "Burma", "São Paulo" all now findable via multi-term search
- **New capability:** Geographic concepts, biomes, watersheds, and geopolitical groupings are now handled
- **Extensibility:** Adding a new geometry source is a single `register_source()` call
- **Test coverage:** 4 → 83 tests, including 16 from observed production failures and 7 named geographic concept tests (The Amazon, The Rockies, The Levant, Colombian coastline, The Sundarbans, and others)
- **Determinism:** Same input always produces same output (no LLM randomness in scoring)

### Negative

- **Flash Lite dependency:** Normalization adds a runtime dependency on Google AI. Mitigated by timeout + passthrough fallback.
- **Concept expansion quality:** Depends on Flash Lite's geographic knowledge, which may be incorrect for obscure regions. Mitigated by the 24h cache (wrong answers are at least consistent) and the coverage note (user is informed).
- **is_concept misclassification:** Flash Lite may occasionally set `is_concept=True` for a real named place (e.g., "Borneo" is both a named island and a geographic concept). Mitigated by the concept expansion re-querying the DB — real named places will still be found as expanded results.
- **Scorer lacks contextual reasoning:** The old LLM could use the question context ("deforestation" → prefer tropical regions). The scorer uses only string matching and hierarchy. Mitigated by `check_multiple_matches` asking the user for ambiguous cases.
- **Multi-term UNION query size:** With 3-4 search terms × 5 source tables, the UNION query has 15-20 subqueries. PostGIS handles this well but it's more complex SQL. Mitigated by `DISTINCT ON` deduplication keeping the result set small.

### Neutral

- **Backward compatibility:** `SOURCE_ID_MAPPING`, `SUBREGION_TO_SUBTYPE_MAPPING`, and `format_id()` are preserved as computed exports. Deprecated `aoi`/`subtype` state fields are still set alongside `aoi_selection`. Removal planned for a follow-up PR.
- **Test DB seeding:** Integration tests now require a PostGIS database seeded with ~114 geometry rows (countries, states, districts, protected areas, landmarks) including newly added Levant countries, Rocky Mountain states, Bangladesh, West Bengal, and Colombian coastal departments. A SQL seed script is used; the full ingestion pipeline is not required for tests.

## Files changed

| File | Change |
|---|---|
| `src/shared/aoi/__init__.py` | New — public API |
| `src/shared/aoi/models.py` | New — AOI, AOISelection, enums |
| `src/shared/aoi/registry.py` | New — AOISourceConfig, 5 registrations |
| `src/agent/tools/aoi_normalizer.py` | New — normalizer + concept expansion; `is_concept` field added |
| `src/shared/geocoding_helpers.py` | Modified — constants from registry |
| `src/agent/tools/data_handlers/analytics_handler.py` | Modified — registry lookup |
| `src/agent/tools/pick_aoi.py` | Modified — scorer, multi-term search, 4-phase flow |
| `tests/tools/test_pick_aoi.py` | Rewritten — 83 tests across 10 categories |
| `tests/agent/test_graph.py` | Modified — mock updates |
