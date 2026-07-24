# Insight chart colors — implementation plan

*Status: agreed design. Written 2026-07-24. Phase 1 and phase 2 are both
implemented (same day) on top of each other in the existing phase-1
branches/PRs (backend PR #771, frontend PR #615) — phase 3 cleanup is not yet
started. This document is self-contained: a fresh session can pick up any
phase from here without prior conversation context.*

## Problem

Chart and category colors for insights (land cover classes, tree-cover-loss
drivers, dataset series colors, divergent GHG colors) are currently defined
**only in the frontend** (`project-zeno-next`), keyed by literal English
strings, and applied client-side when rendering `ChartWidget`. Two independent
frontend files hold overlapping-but-unsynced color data:

- `app/config/chartColorMappings.ts` — `CHART_COLOR_MAPPING` (category → hex,
  per chart field), `DATASET_SERIES_COLORS` (dataset name → hex),
  `DATASET_DIVERGENT_COLORS` (dataset name → {positive, negative})
- `app/constants/datasets.ts` — map-legend `legend.items` (label → hex), same
  categories, different casing, at least one confirmed drift bug (GHG dataset
  keyed `2001-2024` here vs `2001-2025` in `chartColorMappings.ts`)

This breaks once the agent translates category labels for non-English users:
the frontend's color lookup is an exact string match against the (now
translated) category value, so the same bucket gets a different color per
language, or falls back to the generic cycling palette.

The backend today has **no color values anywhere** in the chart pipeline —
`InsightChart.color_field` only names *which column* drives color grouping,
not an actual color. `chart_data` is a flat `List[dict]` with no schema
enforcing a stable, language-independent key: once the code-executor LLM
writes a translated string into a row, the English category identity is gone.

## Decisions already made (don't re-litigate)

1. **Colors reach the frontend via a sibling `color_map` field**, not inlined
   per-row. `InsightChart` gains `color_map: Dict[str, str]` (category slug →
   hex) alongside the existing `chart_data` rows, plus `series_color` and
   `divergent_colors` for non-categorical single-series/diverging charts.
2. **Stable category key = English slug, uniformly.** Verified by calling the
   live analytics API directly (not just the test fixtures, which turned out
   to be synthetic/inconsistent placeholders): **none** of the three
   categorical datasets (Global Land Cover, Tree Cover Loss by Dominant
   Driver, SBTN Natural Lands Map) return a numeric class code — only string
   labels (`natural_lands_class`, `driver`, `land_cover_class`), with no
   `class_id` field in the real response at all. (An earlier draft of this
   doc incorrectly claimed SBTN Natural Lands returns a numeric `class_id`
   alongside the label — that was an artifact of a synthetic test fixture,
   not real API behavior; corrected 2026-07-24.) So a numeric-first design
   isn't viable for any of them — uniform English slugs, defined by us in
   the catalog YAML (where the grouping rules already live), is the only
   option and is simpler anyway.
   Also verified: the SBTN Natural Lands API returns a **variable** number of
   classes per AOI (18 for Colombia, 19 for Brazil in live tests) — up to
   the ~20 in the tile colormap — never a collapsed 2-row "Natural"/
   "Non-natural" response. That grouping is purely an LLM/code-executor
   post-processing step per the catalog's `code_instructions`, not something
   the API does.
3. **Unify chart colors and map-legend colors** on one backend-owned registry,
   not two independently-maintained frontend files. This also fixes the
   existing GHG dataset-name drift bug as a side effect.
4. **No existing metadata channel to extend** — verified there is no
   `datasets`/`catalog`/`legend` router in `src/api/routers/`, and the
   frontend's `constants/datasets.ts` is 100% static, never fetched from the
   backend for anything. `GET /api/metadata` is unrelated (geocoding/model
   info). Unifying means building a **new** endpoint from scratch.
5. **Color resolution is deterministic Python, not LLM output.** The
   code-executor LLM must never be asked to invent/emit hex codes — it only
   needs to emit a stable slug column. A plain Python post-processing step
   looks up colors from the registry. Any slug not found in the registry
   (a genuinely novel LLM-invented grouping, e.g. combining "Cropland" +
   "Cultivated grasslands" into "Agriculture") falls back to a deterministic
   hash/index-based pick from a generic palette — consistent across
   regenerations of the same insight, never random.

## Architecture

### A. Canonical palette registry (backend, single source of truth)

Extend the existing dataset catalog YAMLs
(`src/agent/datasets/catalog/*.yml`) with new top-level keys:

```yaml
categories:        # only on datasets with categorical breakdowns
  - slug: tree_cover
    label_en: "Tree cover"
    color: "#246E24"
  - slug: cropland
    label_en: "Cropland"
    color: "#fff183"
  ...
series_color: "#DC6C9A"          # only on single-series datasets
divergent_colors:                # only on datasets with pos/neg semantics
  positive: "#9a65c0"
  negative: "#137375"
```

This sits in the same file as the existing numeric `colormap` (embedded in
`tile_url`, used for raster tile rendering — untouched, still numeric because
that's a hard technical constraint of pixel rendering, not a design choice).
One file, one edit point, so a human editing colors for a dataset sees both
representations together and can't let them drift apart.

Verified safe to add: `src/agent/datasets/config.py::_load_datasets()` only
checks for **required** columns (`dataset_id, dataset_name, description,
selection_hints, content_date, context_layers, parameters`) — it does not
reject unknown keys, so `categories`/`series_color`/`divergent_colors` are
inert additions until explicitly read by new code.

### B. New endpoint: `GET /api/datasets/catalog`

Reads `DATASETS` (from `src/agent/datasets/config.py`) and returns structured
JSON per dataset: `dataset_id`, `dataset_name`, `categories`, `series_color`,
`divergent_colors`. This becomes the frontend's source for map-legend colors,
replacing the hardcoded `legend.items` in `constants/datasets.ts`. Ships
independently of the agent-pipeline work below — zero risk to chart
generation, and fixes the existing GHG drift bug on its own.

### C. Stable slug threaded through chart generation (not yet built — phase 2)

Today `dataset_id` is available on `state["dataset"]`
(`DatasetSelectionResult.model_dump()`, see `src/agent/subagents/pick_dataset/`)
at the point `generate_insights` runs, but is **dropped** before reaching the
code-executor prompt or `InsightChart` — verified in
`src/agent/subagents/analyst/tool.py::Analyst._resolve_charts()` (lines
365-381), which only forwards `code_instructions`, `prompt_instructions`,
`cautions`, `context_layer`.

Phase 2 must:
- Thread `dataset_id` through `_resolve_charts` → `InsightChart`.
- Update the `EXECUTOR_WORKFLOW` prompt (`src/agent/subagents/analyst/prompts.py`)
  so that when the code-executor groups/renames raw API category strings
  (e.g. "combine cropland + cultivated grassland into Agriculture", per each
  catalog's `code_instructions`), it emits a stable English slug column
  alongside the translated display label it writes today. Naming convention
  TBD (e.g. every categorical column `X` gets a sibling `X__slug` column).

### D. Deterministic color resolution step (not yet built — phase 2)

After `chart_data` is produced, a plain Python function looks up the registry
(same YAML data from A, via the loader from B) by `dataset_id` + slug column,
and attaches `color_map` / `series_color` / `divergent_colors` onto
`InsightChart`. Unrecognized slugs get a deterministic fallback color (hash of
the slug, or index-based cycling), never random.

### E. Schema/DB/API plumbing (not yet built — phase 2)

- `InsightChart` (`src/agent/subagents/analyst/charts/model.py`): add
  `color_map: Dict[str, str] = {}`, `series_color: Optional[str] = None`,
  `divergent_colors: Optional[dict] = None`.
- `InsightChartOrm` (`src/api/data_models.py`): new JSONB column(s) + alembic
  migration in `db/alembic/versions/`.
- `to_orm_kwargs()` / `to_frontend_dict()`, `InsightChartResponse`
  (`src/api/schemas.py`) updated to match.
- `update_insight_display` / `DisplayReviser`
  (`src/agent/subagents/analyst/display_reviser.py`) re-runs color resolution
  when chart type/fields are revised.

### F. Frontend cutover (partially phase 1, rest phase 2)

- **Phase 1**: legend components (`app/components/legend/useLegendHook.tsx`
  etc.) and `constants/datasets.ts` fetch categories/colors from the new
  `/api/datasets/catalog` endpoint instead of hardcoded `legend.items`.
- **Phase 2**: `ChartWidget.tsx` / `formatCharts.tsx` prefer backend-supplied
  `colorMap`/`seriesColor`/`divergentColors` on the insight response; local
  `chartColorMappings.ts` demotes to fallback-only (pre-migration insights,
  genuinely unmapped slugs), then gets deleted once verified.

## Concrete color data to port (phase 1 source of truth)

Ported verbatim from `chartColorMappings.ts` / `constants/datasets.ts` — no
new color design, just consolidation. Slugs are new (snake_case of the
English label), everything else is an existing hex value.

| dataset_id | dataset_name | color data |
|---|---|---|
| 0 | Global all ecosystem disturbance alerts (DIST-ALERT) | series_color `#f69` |
| 1 | Global land cover | categories: see below |
| 2 | Global natural/semi-natural grassland extent | series_color `#ff9916` |
| 3 | SBTN Natural Lands Map | categories: see below |
| 4 | Tree cover loss | series_color `#DC6C9A` |
| 5 | Tree cover gain | series_color `#3F08F5` |
| 6 | Forest greenhouse gas net flux | divergent_colors: positive `#9a65c0`, negative `#137375` |
| 7 | Tree cover | series_color `#97BD3D` |
| 8 | Tree cover loss by dominant driver | categories: see below; series_color `#DC6C9A` (used for non-pie chart types) |

**dataset_id 1 — Global land cover categories:**
`tree_cover` #246E24, `short_vegetation` #B9B91E, `wetland_short_vegetation`
#74D6B4 ("Wetland – short vegetation"), `bare_and_sparse_vegetation` #FEFECC
("Bare and sparse vegetation"), `water` #6BAED6, `snow_ice` #ACD1E8
("Snow/ice"), `cropland` #fff183, `cultivated_grasslands` #FFCD73, `built_up`
#e8765d ("Built-up").

**dataset_id 3 — SBTN Natural Lands Map categories (21):**
`natural_forests` #246E24, `natural_peat_forests` #093D09,
`natural_peat_short_vegetation` #99991A, `mangroves` #06A285,
`wet_natural_forests` #589558, `wet_natural_short_vegetation` #DBDB7B,
`natural_short_vegetation` #B9B91E, `natural_water` #6BAED6, `bare` #FEFECC,
`snow` #ACD1E8, `crop` #D3D3D3, `built` #D3D3D3, `non_natural_tree_cover`
#D3D3D3, `non_natural_short_vegetation` #D3D3D3, `wet_non_natural_tree_cover`
#D3D3D3, `non_natural_peat_tree_cover` #D3D3D3,
`wet_non_natural_short_vegetation` #D3D3D3, `non_natural_peat_short_vegetation`
#D3D3D3, `non_natural_water` #D3D3D3, `non_natural_bare` #D3D3D3, `other`
#D3D3D3.

Note: this dataset's API returns **only** the string `natural_lands_class`
label, no numeric code (see decision 2) — the numeric class codes only exist
in the raster tile colormap in `sbtn_natural_lands_map.yml`, unrelated to
this registry. The API also returns a variable subset of these 21 classes
per AOI (never all of them at once, never a collapsed 2-row response), so
the code-executor/frontend must expect partial coverage, not assume every
category always appears.

**Map legend exception**: this dataset's map legend (`constants/datasets.ts`
in project-zeno-next) intentionally curates the 21 fine-grained classes down
to 11 display rows (grouping all non-natural classes, which share the same
grey `#D3D3D3`, into a single "non-natural" row) — a deliberate simplification
because the fine-grained non-natural breakdown is less relevant there. The
catalog YAML marks this with `legend_categories: false`
(`src/agent/datasets/palette.py` → `DatasetPalette.legend_categories`), which
tells the frontend's `applyPaletteOverride`
(`app/components/legend/useLegendHook.tsx`) to leave this dataset's
hand-curated legend `items` untouched rather than expanding it to the full
category list. Chart colors are unaffected — this flag only controls legend
*display grouping*, not the color values themselves, which still come from
this same registry.

**dataset_id 8 — Tree cover loss by dominant driver categories:**
`logging` #52A44E, `shifting_cultivation` #E9D700, `wildfire` #885128,
`other_natural_disturbances` #3B209A, `settlements_infrastructure` #A354A0
("Settlements & Infrastructure"), `hard_commodities` #E58074,
`permanent_agriculture` #E39D29, `unknown` #D3D3D3.

## Known gaps (pre-existing, not fixed by this plan)

- When the code-executor groups raw categories per a catalog's
  `code_instructions` (e.g. "Agriculture" = cropland + cultivated grasslands;
  "Natural"/"Non-natural" for SBTN natural lands), the resulting bucket name
  has **no registry entry** — this is already true of today's frontend maps
  and isn't a regression. These fall through to the deterministic fallback
  palette (decision 5). A future pass could add these grouped-bucket slugs to
  the registry explicitly if they turn out to be common.

## Build order

1. **Phase 1 (done)**: registry data (A) + loader + new endpoint (B) +
   frontend legend fetch (part of F). Ships independently, fixes the GHG
   drift bug, zero risk to the agent/LLM pipeline.
2. **Phase 2 (done)**: slug threading (C) + resolver (D) + schema/DB (E) +
   chart-side frontend cutover (rest of F).
   - C/D: `EXECUTOR_WORKFLOW` (`src/agent/subagents/analyst/prompts.py`) now
     instructs the code executor to emit a `{column}__slug` sibling column
     next to any categorical color column, using canonical slugs passed in
     via a new `category_slug_hints` section of the analysis prompt
     (`Analyst._resolve_charts` in `tool.py`, built from
     `get_dataset_palette(dataset_id)`). A new deterministic resolver,
     `resolve_chart_colors()` in
     `src/agent/subagents/analyst/charts/color_resolver.py`, attaches
     `color_map` (slug -> hex, with a hashed fallback for unrecognized
     slugs), `series_color` and `divergent_colors` onto each `InsightChart`
     after the executor runs. `update_insight_display` re-runs this resolver
     when a revision changes which column drives color, using the
     `dataset_id` persisted on the original chart.
   - E: `InsightChart` (model + ORM + `InsightChartResponse`) gained
     `dataset_id`, `color_map`, `series_color`, `divergent_colors` — see
     migration `d4f7b1e9a3c2_add_chart_color_registry_fields`.
   - F (chart side): `formatChartData` (project-zeno-next
     `app/utils/formatCharts.tsx`) now takes an optional `colorOverrides`
     param (`colorMap`/`seriesColor`/`divergentColors`) read off each
     `InsightWidget`/`ChartDTO`, preferred over the local
     `chartColorMappings.ts` config. Pie-chart row coloring resolves via the
     row's `{field}__slug` value when present, falling back to the raw field
     value for chart data with no slug column (e.g. pre-migration insights).
3. **Phase 3 (cleanup, not started)**: delete dead frontend color code
   (`chartColorMappings.ts`) once phase 2 is verified in production for a
   while.

## Out of scope (deliberately)

- Redesigning any color values — this is pure consolidation.
- Backfilling colors onto already-persisted insights — the frontend fallback
  covers old data, no migration script planned.
- Solving the "grouped bucket has no color" gap above.
