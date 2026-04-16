# ADR-002: FAO FRA 2025 Tool — National Forest Statistics

**Status:** Accepted
**Date:** 2026-03-24
**Authors:** Adam Pain, Claude

## Context

Project Zeno's primary data path routes all forest analysis through three tools in sequence: `pick_aoi → pick_dataset → pull_data`. This pipeline fetches remote-sensing pixel data from the GFW analytics API at sub-national resolution with user-defined date ranges.

A distinct and commonly requested class of query is not well served by this pipeline: officially-reported national forest statistics such as total forest area, carbon stocks, growing stock volume, and forest ownership. These figures come from the FAO Global Forest Resources Assessment (FRA) 2025 — a standardised country inventory covering 236 countries, compiled every five years.

### Problems with routing FRA queries through the existing pipeline

**1. No matching GFW dataset**

`pick_dataset` searches the dataset registry for a semantic match. FRA national statistics are not a GFW remote-sensing layer — they are country-reported inventory data. The dataset registry contains no entry for FRA, so `pick_dataset` would either hallucinate a match or return nothing.

**2. Wrong data granularity**

`pull_data` targets the GFW analytics API and returns pixel-aggregated data at district/state resolution. FRA data is national-level only. There is no sub-national FRA API.

**3. Date range incompatibility**

`pull_data` accepts arbitrary date ranges and returns continuous time-series. FRA data has fixed reporting years (1990, 2000, 2010, 2015, 2020, 2025). Asking the user for a date range before fetching FRA data is misleading and unnecessary.

**4. Missing chart/presentation guidance**

`generate_insights` reads `state["dataset"]` to get `presentation_instructions`, `code_instructions`, and `cautions`. Since the existing pipeline requires `pick_dataset` to set this state, FRA queries would arrive at `generate_insights` with `state["dataset"] = None`, causing an `AttributeError` and — if patched — producing charts with no domain-specific guidance about FRA terminology, fixed reporting years, or the distinction between net forest area change and deforestation.

### Why FAO FRA 2025 specifically

FRA 2025 is the most recent cycle, published October 2024. It covers 22 reporting tables, includes a data tier system documenting reliability, and offers a public REST API (`https://fra-data.fao.org/api`). The API returns nested JSON keyed as `assessment → cycle → country → table → year → variable → raw`.

## Decision

### 1. Introduce `query_fra_data` as a parallel tool to `pull_data`

Add a new `@tool("query_fra_data")` that bypasses `pick_dataset` entirely and routes directly from `pick_aoi`:

```
Remote-sensing:   pick_aoi → pick_dataset → pull_data → generate_insights
FAO/FRA:          pick_aoi → query_fra_data → generate_insights
```

The tool:
- Reads country ISO3 codes from `state["aoi_selection"]["aois"][*]["src_id"]` — the same state that `pick_aoi` writes
- Calls the FAO FRA public API for the requested variable and table
- Returns a `Command` updating `statistics`, `messages`, and `dataset`

**Rationale:** A separate tool with a clear docstring is the idiomatic LangGraph approach. It allows the agent's router (the LLM) to choose the correct path based on query intent. It avoids polluting `pull_data` with a special case for national statistics.

**Alternative considered:** Extending `pull_data` with an `fra` flag. Rejected because `pull_data` is tightly coupled to the GFW analytics API schema; adding a conditional code path would make both tools harder to maintain and harder for the LLM to route correctly.

### 2. Variable map as a separate module (`variable_map.py`)

User-facing variable names (e.g. `forest_area`, `carbon_stock`, `ownership`) are mapped to FAO API table names and variable filter lists in a dedicated `variable_map.py` module:

```python
VARIABLE_MAP: dict[str, dict] = {
    "forest_area": {
        "table": "extentOfForest",
        "variables": ["forestArea", "naturallyRegeneratingForest", "plantedForest", "primaryForest"],
        "unit": "1000 ha",
        "description": "...",
    },
    ...  # 21 variables total
}
```

The tool docstring enumerates all valid variable names. The LLM picks the appropriate variable name based on the user's query; `query_fra_data` validates against `VARIABLE_MAP` and returns an error message if the variable is unrecognised.

**Rationale:** Separating the mapping from the tool logic means new variables can be added without touching the tool's core fetch/parse path. The module is independently testable. Empty `variables: []` in the map means "fetch all variables for this table" — the FAO API supports this natively.

### 3. Flat `statistics["data"]` structure

`generate_insights` calls `pd.DataFrame(statistics_entry["data"])`, where `statistics_entry` is one element of the `statistics` list. The `data` field must therefore be directly a list of flat dicts:

```python
# Correct — data is a list of records
{"dataset_name": "FAO FRA 2025 — ...", "data": [{"year": 1990, "variable": "forestArea", "value": 493538.0, ...}]}

# Wrong — data is a nested dict (causes TypeError: unhashable type: 'dict')
{"dataset_name": "FAO FRA 2025", "data": {"variable": "forest_area", "data": [...]}}
```

Each record has fields: `year`, `variable`, `value`, `odp` (Open Data Platform flag), `country` (ISO3), `aoi_name` (human-readable). Variable-level metadata (unit, description) is surfaced through the `dataset_name` field.

### 4. Inject FRA dataset config into `state["dataset"]`

`query_fra_data` loads `fao_fra_2025.yml` at import time via the existing `DATASETS` registry and injects it into state via the `Command` update:

```python
update["dataset"] = _FRA_DATASET_CONFIG
```

This ensures `generate_insights` receives the same `presentation_instructions`, `code_instructions`, and `cautions` that GFW datasets receive through `pick_dataset`. No changes to `generate_insights` are required for the happy path; only a `None`-guard was added for the case where `state["dataset"]` is absent.

**Rationale:** Reuses the existing YAML-based dataset instruction system without modification. The FRA config sits alongside other dataset YAMLs and follows the same schema, so the same tooling (dataset registry, `generate_insights` prompt builder) works for both remote-sensing and FRA data.

### 5. FAO FRA dataset YAML (`fao_fra_2025.yml`)

A full dataset YAML was created with:

- **`presentation_instructions`** — terminology rules: use "forest area change" not "deforestation"; note data is country-reported not satellite-derived; fixed reporting years; no cross-edition FRA comparisons; FAO "forest" ≠ GFW "tree cover"
- **`code_instructions`** — chart type rules by variable: line for trends, stacked-bar for composition, grouped-bar for multi-country; year axis always treated as categorical; never interpolate between reporting years
- **`cautions`** — data quality warnings: self-reported, methodology varies by country; each FRA cycle is independent; net change ≠ deforestation; subregional aggregates may not sum due to gap-filling; disturbance data time coverage is limited
- **`selection_hints`** — guides `get_capabilities` and any future `pick_dataset` integration

### 6. Agent prompt routing rules

The system prompt was updated with explicit routing guidance:

```
ROUTING — pull_data vs query_fra_data:
- pull_data: remote-sensing pixel data, sub-national analysis, time-series with custom date ranges
- query_fra_data: country-reported national statistics, official government inventories,
  FAO/FRA questions, questions about total national forest area, nationally-reported
  carbon stock or biomass, forest ownership or management categories.
  Does NOT need a date range — FRA uses fixed reporting years.

NOTE: For query_fra_data, you do NOT need AOI + dataset + date range. You only need
a country AOI. Do not ask the user for a dataset or date range before calling query_fra_data.
```

## Consequences

### Positive

- **New capability:** FRA national statistics (forest area trends, carbon, biomass, ownership, disturbances, and 15 other variables) are now answerable for any of the 236 countries in FRA 2025
- **Correct routing:** Clear LLM instructions and a typed tool docstring prevent the agent from routing FRA queries through the GFW pipeline (or refusing them)
- **Chart quality:** `generate_insights` now receives FAO-specific presentation and chart instructions, preventing common errors (interpolating between reporting years, labelling net change as deforestation, conflating FAO and GFW forest definitions)
- **Extensibility:** Adding a new FRA variable is a one-line entry in `variable_map.py`; the fetch/parse path is unchanged
- **Latency:** The FAO FRA API is fast (typically < 2s) and the tool adds no LLM calls beyond the main agent loop

### Negative

- **External API dependency:** `query_fra_data` depends on the FAO FRA public API being available. No caching or fallback is implemented. If the API is unreachable the tool returns a user-facing error and stops
- **Country-level only:** FRA data is national aggregates. Sub-national questions (e.g. "forest area in Amazonas state") cannot be answered by this tool; the agent must redirect to `pull_data`
- **Fixed reporting years:** Users expecting annual or monthly data will be disappointed. The agent prompt and tool error messages communicate this, but it is a hard constraint of the underlying dataset
- **LLM variable selection:** The LLM must pick the correct variable name from the docstring. Ambiguous queries (e.g. "how much forest does Brazil have" could map to `forest_area` or `forest_area_change`) depend on the LLM making a reasonable choice; the agent can always re-call the tool with a different variable

### Neutral

- **`generate_insights` `None`-guard:** A defensive `(state.get("dataset") or {})` guard was added for the `dataset` lookups in `generate_insights`. This is a general robustness improvement — any future tool that skips `pick_dataset` will not crash `generate_insights`
- **`statistics["data"]` contract:** The flat-list-of-dicts shape of `statistics["data"]` was an implicit contract; this implementation makes it explicit in the codebase. Existing tools (`pull_data`) already conform; only FRA required care

## Files changed

| File | Change |
|---|---|
| `src/agent/tools/query_fra_data.py` | New — `@tool("query_fra_data")` implementation |
| `src/agent/tools/fao_client.py` | New — async httpx client for FAO FRA API |
| `src/agent/tools/variable_map.py` | New — 21-variable map from user names to API table identifiers |
| `src/agent/tools/datasets/fao_fra_2025.yml` | New — dataset config with presentation, code, and caution instructions |
| `src/agent/tools/__init__.py` | Modified — export `query_fra_data` |
| `src/agent/graph.py` | Modified — add tool to list; update system prompt with routing rules |
| `src/agent/tools/generate_insights.py` | Modified — `None`-guard on `state.get("dataset")` |
| `tests/tools/test_fra.py` | New — 19 tests: `_parse_response`, `fetch_fra_data`, `query_fra_data`, variable map |
