# Near-real-time monitoring section — implementation plan

*Status: proposed. Scope: backend (`wri/project-zeno`) plus the frontend
contract. Related docs: `dashboards-mvp-plan.md`,
`dashboards-map-widgets-handoff.md`.*

## 1. Goal

Give the frontend one button that adds a near-real-time (NRT) monitoring
**section** to a dashboard. The section holds three widgets for the
dashboard's area and one date range:

| # | Widget | Content |
|---|--------|---------|
| 1 | `insight` | Line chart of alert area (ha) per month, by confidence tier |
| 2 | `map` | Integrated alerts tile layer for the same date range |
| 3 | `map` | Sentinel-2 mosaic for the end of the same date range |

The section title and description are written by the LLM from the chart data.
The description is the summary: it says what the section shows and states the
key figures.

Alerts come from the **Integrated alerts** dataset (`dataset_id: 11`,
`src/agent/datasets/catalog/integrated_alerts.yml`). The chart comes from the
default (deterministic) insight generator for that dataset
(`IntegratedAlertsChartGenerator`), not from the analyst subagent.

## 2. What exists today

| Part | State | File |
|------|-------|------|
| Default alerts chart | Done | `src/api/services/charts/integrated_alerts.py` |
| Deterministic analysis job | Done | `src/api/routers/analyze.py`, `src/api/services/analysis_job.py` |
| Insight persistence | Done | `src/api/repositories/insight_writer.py` |
| Dashboard sections (title, description, position) | Done | `src/api/repositories/dashboard_writer.py` |
| Map widget config contract (`dataset` / `imagery`) | Done | `src/api/schemas.py`, `src/agent/tools/add_map_widget.py` |
| Sentinel-2 mosaic build | Done | `src/api/services/mosaic.py` |
| Job status polling | Done | `src/api/routers/jobs.py` |

Four gaps stop a "one-click" build:

1. **Sections have no type.** The frontend cannot tell an NRT section from a
   user-made section.
2. **A dataset tile layer can only be resolved by the LLM path.**
   `get_tile_services_for_dataset()` in
   `src/agent/subagents/pick_dataset/tool.py` needs a `selection_result`
   object from the dataset-selection LLM and a pandas row. No API caller can
   get a tile URL for a dataset and a date range.
3. **The mosaic endpoint does not return tile URLs.** `MosaicResult` has
   `tile_url` and `tilejson_url` properties, but `MosaicCreateResponse`
   (`src/api/models.py`) drops them. A REST caller gets a `mosaic_id` that it
   cannot render.
4. **Nothing composes the three widgets.** Each widget needs a different
   slow call (analytics pull, STAC search and mosaic build, LLM text). The
   frontend must not chain them.

## 3. Design decisions

**D1 — The unit is a section, not a widget.** `dashboard_sections` gets a
`type` column. The first two values are `default` and `nrt-monitoring`. The
type is a render hint for the frontend and a marker for later features
(refresh, subscribe). Widgets keep their existing types and config shapes.

**D2 — Alerts and imagery stay in two map widgets.** The map widget config
keeps exactly one of `dataset` or `imagery`. The frontend renders both
widgets with code that it already has. No schema change, no layer stacking.

**D3 — One composite endpoint, one job.** The endpoint starts a background
job, like `POST /api/analyze`. The frontend does one call, polls
`GET /api/jobs/{id}`, then refetches the dashboard. All work happens in one
place, and one place owns the NRT recipe.

**D4 — The section title and description are generated.** One `SMALL_MODEL`
call writes both from the chart rows, the area name, the date range and the
dataset's `presentation_instructions`. If the call fails, the code writes a
templated title and description instead. A failed LLM call must not fail the
job.

**D5 — Satellite imagery is optional.** Mosaics are limited to 50,000 km²
(`MAX_AOI_AREA_KM2`), and a search can find no scenes. If the mosaic fails,
the job creates the section with the other two widgets and reports the
reason. Only an analytics failure fails the job.

**D6 — An NRT section is sealed.** Neither the user nor the agent can change
its title, its description, its widgets or the order of its widgets. The
section is a machine-built record of one area and one date range, so an edit
would make the label untrue. The rules and the enforcement points are in
section 4.10. The user keeps two actions: delete the whole section, and build
a new one.

## 4. Changes

### 4.1 Section type (database)

- `src/api/data_models.py` — add to `DashboardSectionOrm`:
  ```python
  # How the section was built and how the frontend renders it:
  # "default" (user- or agent-composed) or "nrt-monitoring".
  type = Column(String, nullable=False, server_default="default")
  ```
- New Alembic revision in `db/alembic/versions/`: add the column with the
  server default, so existing rows become `default`.
- `src/api/schemas.py`:
  - `_SECTION_TYPES = ("default", "nrt-monitoring")` with a validator, in
    the same style as `_WIDGET_TYPES`.
  - `DashboardSectionCreateRequest.type` (default `"default"`).
  - `DashboardSectionResponse.type`.
  - `DashboardSectionUpdateRequest` does **not** accept `type`. The type
    records how the section was built, so it stays fixed.
- `src/api/repositories/dashboard_writer.add_section()` — add a
  `type: str = "default"` keyword.
- `src/api/routers/dashboards.add_section()` — pass `body.type`.
- `src/agent/tools/add_dashboard_section.py` — no change. Agent-made
  sections stay `default`.

### 4.2 Dataset layer resolution without the LLM

Move the tile-URL rules out of the dataset-selection subagent into a new
module `src/agent/datasets/layers.py`:

```python
@dataclass(frozen=True)
class DatasetLayer:
    dataset_id: int
    dataset_name: str
    tile_url: str
    context_layer: Optional[str]
    context_layers: list[dict]
    parameters: Optional[list[dict]]
    start_date: str
    end_date: str


def resolve_dataset_layer(
    dataset_id: int,
    start_date: str,
    end_date: str,
    *,
    context_layer: Optional[str] = None,
    parameters: Optional[list[dict]] = None,
) -> DatasetLayer: ...
```

The function reads the dataset record from `DATASETS` (a list of dicts) and
keeps the current per-dataset rules:

- eoapi-relative `tile_url` values get `SharedSettings.eoapi_base_url`;
- canopy-cover thresholds for the tree-cover datasets;
- `&start_year=…&end_year=…` for tree cover loss;
- `&start_date=…&end_date=…` for integrated alerts;
- `{year}` substitution for land cover and grasslands.

`get_tile_services_for_dataset()` becomes a thin adapter over this function,
so the chat path produces the same tile URL as before. This keeps one
definition of a dataset layer for both paths, and the widget config that the
NRT job writes is identical to the config that `add_map_widget` writes.

Integrated alerts is the low-risk case: the catalog holds an absolute
`tile_url` on the GFW tiles host, no context layers and no parameters, so the
rule is only the two date parameters.

### 4.3 One definition of the widget config snapshots

`src/agent/tools/add_map_widget.py` holds `_dataset_config()`,
`_imagery_config()` and `_IMAGERY_KEYS`. These are the contract that the
frontend renders. Move them to `src/api/services/widget_configs.py` as:

- `dataset_widget_config(layer: DatasetLayer) -> dict`
- `imagery_widget_config(imagery: ImageryState) -> dict`

`add_map_widget` then projects its agent state onto those types and calls the
same builders. The key allowlist behaviour stays: only render fields reach
the database.

### 4.4 Mosaic tile URLs in the REST response

`src/api/models.py` — add `tile_url: str` and `tilejson_url: str` to
`MosaicCreateResponse`; `src/api/routers/mosaic.py` fills them from the
`MosaicResult` properties. The change is additive, so it breaks no client.
It also lets a frontend build an imagery map widget without the NRT recipe.

### 4.5 The section summary generator

New module `src/api/services/nrt_summary.py`:

```python
class NrtSectionSummary(BaseModel):
    title: str      # <= 60 characters
    description: str  # 2-4 sentences


async def generate_section_summary(
    charts: list[InsightChart],
    aoi_name: str,
    start_date: str,
    end_date: str,
    language: str,
) -> NrtSectionSummary: ...
```

Rules for the prompt:

- Ground every figure in the chart rows. Do not compute new figures.
- State the unit `ha` with every area.
- Name the confidence tiers that the data shows.
- Say that alerts show potential disturbance, not confirmed deforestation.
  The catalog's `presentation_instructions` already carries this wording —
  pass it in, do not repeat it in the prompt.
- Write in the user's preferred language (`language_name()`), as
  `InsightTextGenerator` does.

The generator uses `SMALL_MODEL` with structured output, in the style of
`src/agent/subagents/analyst/text_generator.py`. On any exception, the caller
falls back to a templated title (`"Near-real-time monitoring — {aoi}"`) and a
templated description that states the total area and the date range.

### 4.6 The NRT section service

New module `src/api/services/nrt_monitoring.py`.

```python
@dataclass
class NrtSectionResult:
    section_id: str
    insight_id: str
    widget_ids: list[str]
    warnings: list[str]   # e.g. why the imagery widget is absent
```

Steps:

1. **Area.** Take the first (MVP: only) AOI of the dashboard —
   `source`, `src_id`, `subtype`, `name`.
2. **Dates.** `end_date = today`, `start_date = today - days`
   (`days` default 90, range 1–365). Clamp both with
   `revise_date_range(start, end, INTEGRATED_ALERTS_ID)`
   (`src/agent/datasets/dates.py`), which holds the dataset coverage
   (alerts start on 2023-12-01).
3. **Data and chart.** Call
   `AnalyzeService(AnalyticsHandler(), DETERMINISTIC_GENERATORS).analyze()`
   with `dataset_id=11`. If the pull fails, fail the job. Persist the charts
   with `persist_insight()` — charts only, no narrative, as
   `/api/analyze` does.
4. **Alerts layer.** `resolve_dataset_layer(11, start, end)` →
   `dataset_widget_config()`.
5. **Imagery.** `create_sentinel2_mosaic(MosaicRecipe(...))` with
   `target_date=end_date`, `window_days` and `max_cloud_cover` from the
   request. Catch `AoiTooLargeError`, `NoScenesFoundError`,
   `StacSearchError` and `MosaicNotFoundError`: append the reason to
   `warnings` and continue without the third widget.
6. **Summary.** `generate_section_summary()` over the charts.
7. **Write.** One transaction — see 4.7.

### 4.7 One transactional write

Add `dashboard_writer.add_section_with_widgets(dashboard_id, *, title,
description, type, widgets: list[WidgetSpec])`. It creates the section and
its widgets in a single session, so a half-built section never reaches the
frontend. Widget positions are 0, 1, 2 in the order of the table in section 1.

### 4.8 The endpoint

`src/api/routers/dashboards.py`:

```
POST /api/dashboards/{dashboard_id}/sections/nrt-monitoring
```

- Owner only (`_get_owned_dashboard`), so a non-owner gets 404.
- Body (`NrtSectionCreateRequest`):
  | Field | Default | Notes |
  |-------|---------|-------|
  | `days` | 90 | 1–365; the length of the alert window |
  | `window_days` | 7 | Mosaic search window, 1–183 |
  | `max_cloud_cover` | 20 | Mosaic cloud filter, 0–100 |
  | `title` | null | Overrides the generated title |
  | `description` | null | Overrides the generated description |
  | `force` | false | Build a second section for the same window |
- Returns `JobResponse` with `status: pending`, as `/api/analyze` does.
- `JobType.NRT_SECTION = "nrt_section"` in `src/api/services/job.py`.
- The job writes two resources: `/api/insights/{insight_id}` and
  `/api/dashboards/{dashboard_id}`.
- **Double-click guard.** If the dashboard already has an
  `nrt-monitoring` section for the same date range, the endpoint returns the
  completed job for it and builds nothing, unless `force` is true.

The plain `POST /api/dashboards/{id}/sections` endpoint stays synchronous and
simple. It only gains the optional `type` field.

### 4.9 Agent parity

Add the tool `src/agent/tools/add_nrt_monitoring_section.py`. It calls the
same service, so "monitor this area for me" works in chat. Register the SPEC
in `src/agent/agent_config.py` and add it to the `requires:` list of
`src/agent/skills/skills_md/dashboard.md`, with a line that says when to use
it. The tool returns the usual `dashboard_updated` command, so the frontend
refetch behaviour does not change.

### 4.10 Immutability guardrails

The seal is a product rule, and it will gain section types and exceptions, so
it lives in the application code and in the prompts — not in database
constraints. A trigger or a check constraint would need a migration for every
change to the rule, and it would also block the builder that writes the
section.

#### What is allowed and what is blocked

| Action on an `nrt-monitoring` section | Verdict |
|---|---|
| Read it | Allowed |
| Delete the whole section | Allowed — always with its widgets (see below) |
| Move the section among the other sections (`position`) | Allowed — this orders the dashboard, it does not change the section |
| Publish or unpublish the dashboard (cascades `is_public` to the insight) | Allowed |
| Retitle it or rewrite its description | Blocked |
| Add a widget to it | Blocked |
| Move a widget into it or out of it | Blocked |
| Reorder the widgets in it | Blocked |
| Replace a widget config in it | Blocked |
| Delete one widget from it | Blocked |
| Rewrite the display of the insight it shows (`update_insight_display`) | Blocked |
| Change the section `type` | Blocked — `DashboardSectionUpdateRequest` does not accept the field (4.1) |

Two rules keep the seal whole:

- **Delete always cascades.** `DELETE …/sections/{id}` normally ungroups the
  widgets and keeps them (`delete_widgets=false`). For a sealed section that
  would leave loose, editable NRT widgets at the top level. For these
  sections the delete always removes the widgets, and the `delete_widgets`
  query parameter is ignored. The invariant is: **a widget built by the NRT
  recipe exists only inside its own section.**
- **The type cannot be changed.** If a client could `PATCH` the type to
  `default`, the seal would be one call away from gone. Section 4.1 keeps
  `type` out of the update schema for this reason.

#### Layer 1 — the repository (load-bearing)

The agent tools do not go through the routers; they call
`src/api/repositories/dashboard_writer.py` directly. So the check belongs
there, where both callers meet:

```python
SEALED_SECTION_TYPES = frozenset({"nrt-monitoring"})


class SealedSectionError(Exception):
    # Raised when a write targets a section whose type is read-only.
    def __init__(self, section_id: str, section_type: str): ...
```

Raise it from:

| Function | Condition |
|---|---|
| `update_section` | The section is sealed and the change is not `position` |
| `remove_section` | Never — delete is allowed, but `delete_widgets` is forced to `True` |
| `add_widget` | `section_id` names a sealed section |
| `update_widget` | The widget is in a sealed section, **or** it is being moved into one |
| `remove_widget` | The widget is in a sealed section |

The NRT builder writes a sealed section itself, so
`add_section_with_widgets()` (4.7) takes an internal `allow_sealed=True`
keyword. A later refresh feature uses the same door. No other caller passes
it.

#### Layer 2 — the API

`src/api/routers/dashboards.py` maps `SealedSectionError` to **409 Conflict**
with a stable detail: `"Section is read-only (type: nrt-monitoring)"`. 409
follows the existing use in this router (`DuplicateInsightWidgetError`) and
says what is true: the request conflicts with the state of the resource, not
with the identity of the caller. The order of the checks stays 404 first (the
section or the widget is not on this dashboard), then 409.

#### Layer 3 — the agent

Prompts alone cannot hold the rule — a model retries, and a user can call the
REST API directly. Layer 1 is the guard; this layer exists so the agent
explains the rule instead of hitting an error.

- `src/agent/tools/common.py` — `resolve_section()` refuses to return a
  sealed section as a widget target. The error text says what to do instead:
  put the widget in another section, or rebuild the NRT section.
- Every dashboard tool maps `SealedSectionError` to `error_command()` with
  the same wording, for the paths that do not go through `resolve_section`
  (`move_dashboard_widget`, `edit_dashboard_section`, `edit_text_widget`).
- `src/agent/tools/inspect_view_context.py:439` prints the type and a
  `read-only` marker on each section line, so the model sees the state before
  it acts.
- `src/agent/skills/skills_md/dashboard.md` gains a short rule: near-real-time
  monitoring sections are built in one piece and cannot be edited; to change
  one, delete it and build a new one.
- `src/agent/tools/update_insight_display.py` refuses an insight that a
  sealed section's widget references. This needs a new helper — for example
  `dashboard_access.insight_is_sealed(insight_id)`, a join from the insight
  to its widgets to their sections. Without it the display of the NRT chart
  is editable through the back door.

## 5. Frontend contract

Add `docs/nrt-monitoring-handoff.md`, or extend
`dashboards-map-widgets-handoff.md`, with:

1. `section.type` on every section in `GET /api/dashboards/{id}`.
2. The one-click flow:
   ```
   POST /api/dashboards/{id}/sections/nrt-monitoring  -> job (pending)
   GET  /api/jobs/{job_id}                            -> poll, Retry-After: 1
   GET  /api/dashboards/{id}                          -> render the section
   ```
3. The widget order and the config shape of each widget (no new shapes).
4. Degradation: the section can hold two widgets. The frontend must not
   assume three.
5. The map widgets fit the dashboard area, as all map widgets do.
6. The section is read-only: hide the edit, reorder, delete-widget and
   add-widget controls inside it, and keep the delete-section control. The
   API answers a blocked write with 409 and the detail
   `"Section is read-only (type: nrt-monitoring)"`.

## 6. Tests

Keep the suites small and targeted (`tests/unit`, `tests/api`).

- `tests/unit/agent/test_dataset_layers.py` — `resolve_dataset_layer()` for
  integrated alerts (date parameters), tree cover loss (threshold and years)
  and land cover (`{year}`). Assert that the output equals what
  `get_tile_services_for_dataset()` returned before the move.
- `tests/unit/api/test_nrt_summary.py` — the fallback title and description
  when the model call raises.
- `tests/api/test_nrt_monitoring.py`:
  - the endpoint returns a job, and the job completes;
  - the section has `type: "nrt-monitoring"` and three widgets in order;
  - a mosaic failure gives two widgets and a warning, and the job still
    completes;
  - an analytics failure fails the job and writes no section;
  - a non-owner gets 404;
  - a second call without `force` creates no second section.
- `tests/api/test_dashboards.py` — `type` on section create and read, and
  rejection of an unknown type.
- `tests/api/test_dashboards.py` — the seal, one test per blocked action:
  `PATCH` the section (409), add a widget to it (409), move a widget in and
  out (409), `PATCH` a widget config in it (409), delete one widget (409),
  `PATCH` the section `position` (200), and delete the section with
  `delete_widgets=false` (the widgets go too).
- `tests/unit/api/test_dashboard_writer_sealed.py` — the repository raises
  `SealedSectionError` for each blocked write, and `allow_sealed=True` writes.
- Targeted agent tests — `resolve_section()` refuses a sealed section, and
  `update_insight_display` refuses a sealed insight.
- Mock the analytics API, the STAC search and the model, as
  `tests/api/test_mosaic.py` and the analyze tests do.

## 7. Delivery order

Each step is one PR. Steps 1–3 are independent and can go in parallel.

| PR | Title | Content |
|----|-------|---------|
| 1 | `feat(dashboards): add type to dashboard sections` | 4.1 + migration + tests |
| 2 | `refactor(datasets): resolve dataset layers without the selection agent` | 4.2, 4.3 + parity tests |
| 3 | `feat(mosaic): return tile urls from the mosaic endpoint` | 4.4 |
| 4 | `feat(dashboards): build near-real-time monitoring sections` | 4.5–4.8 + tests |
| 5 | `feat(dashboards): seal near-real-time monitoring sections` | 4.10, layers 1 and 2 + tests |
| 6 | `feat(agent): add the nrt monitoring section tool` | 4.9 + 4.10 layer 3 |
| 7 | `docs(dashboards): nrt monitoring frontend handoff` | Section 5 |

## 8. Open points

- **Cost and rate limits.** One click costs one analytics pull, one STAC
  search or S3 read, and one model call. `/api/analyze` has no quota check
  today, so the new endpoint has none either. Add `enforce_quota` later if
  the traffic needs it.
- **Provenance.** `/api/analyze` writes no `StatisticsOrm` row, so its
  insights carry no dataset or AOI link and
  `GET /api/insights?dataset_id=…&aoi_source=…` does not find them. The NRT
  insight has the same gap. Write the statistics row in the NRT path (and in
  the analyze job) to make these insights findable and reusable.
- **Refresh.** The section is a snapshot: the chart data, the tile URL dates
  and the mosaic are all frozen at build time. Because the section is sealed,
  a refresh is a delete and a rebuild, not an edit. The `force` flag and the
  double-click guard (4.8) already carry that behaviour. A later in-place
  refresh uses the `allow_sealed` door in 4.10.
- **Scope of the seal.** The table in 4.10 lets a sealed section move among
  the other sections, and lets the dashboard publish cascade run. Both are
  open to discussion. To block `position` as well is a one-line change.
- **Area size.** Mosaics stop at 50,000 km². Country-level dashboards get no
  satellite widget. If that case is common, add a scene-free fallback (for
  example a static basemap widget) later.
