# Near-real-time monitoring section — design notes

*Status: implemented. Scope: backend (`wri/project-zeno`). The frontend
contract is in `nrt-monitoring-handoff.md`. Related:
`dashboards-mvp-plan.md`, `dashboards-map-widgets-handoff.md`.*

## 1. What it does

One call adds a **near-real-time (NRT) monitoring section** to a dashboard.
The section holds three widgets for the dashboard's area and one date range:

| # | Widget | Content |
|---|--------|---------|
| 0 | `insight` | Line chart of alert area (ha) per month, by confidence tier |
| 1 | `map` | Integrated alerts tile layer for the same period |
| 2 | `map` | Sentinel-2 mosaic for the end of the same period |

The section's title and description are written by a model from the chart
data; the description is the summary that explains what the section shows
and states the key figures.

Alerts are the **Integrated alerts** dataset
(`src/agent/datasets/catalog/integrated_alerts.yml`). The chart is the
default deterministic insight for it (`IntegratedAlertsChartGenerator`), not
the analyst subagent.

## 2. Decisions

**D1 — The unit is a section, not a widget.** `dashboard_sections.type`
carries `default` or `nrt-monitoring`: a render hint for the frontend and the
handle everything else hangs off.

**D2 — Alerts and imagery stay two map widgets.** A map widget config keeps
exactly one of `dataset` / `imagery`, so the frontend renders both with code
it already had. No schema change, no layer stacking.

**D3 — Synchronous.** The endpoint does the whole build before it answers.
It costs tens of seconds, which is the trade for a caller that makes one
request and renders the response. (A background job with polling was the
alternative; it was rejected deliberately.) One consequence worth keeping in
mind: the request-scoped user id stays bound for the whole build, which the
custom-AOI geometry lookup in the mosaic service depends on.

**D4 — The words are generated, with a fallback.** One `SMALL_MODEL` call
over the chart rows plus the dataset's `presentation_instructions`. Any
failure — exception, blank output — falls back to a templated title and
description (`nrt_summary.fallback_summary`). A model hiccup must not lose a
section whose data is already gathered.

**D5 — Satellite imagery is optional.** Mosaics stop at 50,000 km²
(`MAX_AOI_AREA_KM2`), and a search can find no scenes. Either way the section
is built without the imagery widget and the reason is returned in
`warnings`. Only an analytics failure fails the whole build.

**D6 — An NRT section is sealed.** Neither the user nor the agent can change
its title, description, widgets or widget order. The section is a record of
one build — one area, one period, the data as it was — so an edit would make
its own title untrue. Section 4 covers the enforcement. The user keeps two
actions: delete the whole section, and build another.

## 3. The pieces

| Concern | Where |
|---|---|
| Section type | `data_models.DashboardSectionOrm.type`, migration `a3f5c7e1b204` |
| Layer resolution without an LLM | `src/agent/datasets/layers.py` |
| Widget config snapshots | `src/api/services/widget_configs.py` |
| Title and description | `src/api/services/nrt_summary.py` |
| The recipe | `src/api/services/nrt_monitoring.py` |
| Transactional write | `dashboard_writer.add_section_with_widgets()` |
| Endpoint | `POST /api/dashboards/{id}/sections/nrt-monitoring` |
| Agent parity | `src/agent/tools/add_nrt_monitoring_section.py` |

Three refactors carry their own weight beyond this feature:

- **`resolve_dataset_layer()`** lifts the tile-URL rules (thresholds, year
  substitution, date parameters, the eoapi host) out of the dataset-selection
  subagent, where they needed an LLM selection object and a pandas row.
  `get_tile_services_for_dataset()` is now a thin adapter over it, so a layer
  resolved by a recipe and one resolved in chat are identical. The adapter
  passes its *candidate row* rather than letting the function read the
  catalog: that row's context layers have already been filtered to those
  covering the selected area, and resolving from the catalog would quietly
  undo the filter.
- **`widget_configs`** holds the map-widget snapshot projections that used to
  live inside `add_map_widget`. Same explicit key allowlist, now shared, so
  the prose fields of a dataset record still cannot reach the database.
- **`_visible_insights()`** in the dashboards router is the insight-expansion
  rule that used to be inline in `get_dashboard`. Sharing it means a widget's
  payload does not depend on which endpoint returned the dashboard — the NRT
  response is renderable without a follow-up GET.

Plus one small addition: `MosaicCreateResponse` now returns the `tile_url`
and `tilejson_url` it already derived, so a REST caller gets something it can
render instead of a bare `mosaic_id`.

## 4. The seal

The rule lives in the application, not in database constraints: it is product
policy that will grow types and exceptions, and a constraint would also block
the builder that writes these sections.

### What is allowed and what is blocked

| Action on an `nrt-monitoring` section | Verdict |
|---|---|
| Read it | Allowed |
| Delete the whole section | Allowed — always with its widgets |
| Reorder it among the other sections (`position`) | Allowed — orders the dashboard, does not change the section |
| Publish the dashboard (cascades `is_public` to the insight) | Allowed |
| Retitle it, rewrite its description | Blocked |
| Add a widget to it | Blocked |
| Move a widget into or out of it | Blocked |
| Reorder or reconfigure its widgets | Blocked |
| Delete one of its widgets | Blocked |
| Restyle the insight it shows (`update_insight_display`) | Blocked |
| Change its `type` | Blocked — not in the update schema |

Two rules keep it whole, and both are load-bearing:

- **Delete always cascades.** `remove_section` normally ungroups the widgets
  and keeps them; for a sealed section that would leave loose, *editable*
  NRT widgets at the top level, so the flag is overridden. The invariant is
  that a widget the recipe built exists only inside its own section.
- **The type cannot be changed.** `DashboardSectionUpdateRequest` omits
  `type` deliberately — a retype to `default` would be one PATCH away from
  unsealing.

### Layer 1 — the repository (the actual guard)

The agent tools never pass through the routers; they call `dashboard_writer`
directly. So the check sits where both callers meet:
`SEALED_SECTION_TYPES` and `SealedSectionError`, raised from
`update_section` (unless the change is only `position`), `add_widget`,
`update_widget` (both ends of a move) and `remove_widget`. The recipe's own
write uses `add_section_with_widgets`, and `add_widget` takes an internal
`allow_sealed` for a future refresh.

### Layer 2 — the API

`_sealed_conflict()` maps the error to **409** with a stable
`"Section is read-only (type: nrt-monitoring)"`. A conflict, not a
permission error: the owner is refused because of what the section *is*, and
the same call against any other section succeeds. Order of checks stays 404
first (not on this dashboard), then 409.

### Layer 3 — the agent

Not load-bearing — a model retries, and a user can call REST directly. This
layer exists so the agent explains instead of erroring:

- `resolve_section()` refuses a sealed section as a widget target, with a
  reply that names the alternative.
- `sealed_error_command()` gives one wording to the paths that only learn at
  the write (`edit_dashboard_section`, `edit_text_widget`,
  `move_dashboard_widget`).
- `format_sections()` and `inspect_view_context` mark sealed sections
  `read-only`, so the model sees the state before it acts.
- `dashboard.md` carries the rule and the "delete and rebuild" answer.
- `update_insight_display` refuses an insight a sealed widget references
  (`dashboard_access.insight_is_sealed()`). This was the one path that could
  rewrite a sealed section's content without touching a dashboard row.

## 5. Tests

| File | Covers |
|---|---|
| `tests/unit/agent/test_dataset_layers.py` | Tile URLs per dataset, and the published-year fallback |
| `tests/unit/api/services/test_nrt_summary.py` | The model output, and every route to the fallback |
| `tests/unit/agent/tools/test_sealed_sections.py` | `resolve_section` refusal, the read-only marker, the reply wording |
| `tests/api/test_nrt_monitoring.py` | The built section, imagery degradation, analytics failure, the double-click guard, `force`, auth |
| `tests/api/test_dashboards.py` | Section `type`, one test per blocked action, reorder still allowed, delete cascade, the insight seal |

## 6. Open points

- **Provenance.** `/api/analyze` writes no `StatisticsOrm` row, so its
  insights carry no dataset or AOI link and
  `GET /api/insights?dataset_id=…&aoi_source=…` does not find them. The NRT
  insight inherits that gap. Writing the statistics row in both paths would
  make these insights findable and reusable.
- **Cost and rate limits.** One call costs an analytics pull, a STAC search
  or S3 read, and a model call. Like `/api/analyze`, it has no quota check.
  Add `enforce_quota` if traffic warrants it.
- **Refresh.** The section is a snapshot, and sealed, so a refresh today is a
  delete and a rebuild. An in-place refresh would go through the
  `allow_sealed` door.
- **Scope of the seal.** Reordering a sealed section and the publish cascade
  are deliberately allowed. Blocking `position` too is a one-line change.
- **Area size.** Country-level dashboards get no satellite widget. If that
  case is common, a scene-free fallback widget would fill the gap.
- **Rollout.** The agent tool is gated: it lives in the `nrt-monitoring`
  skill, which only the **experimental** profile loads. The REST endpoint is
  not gated — the frontend button works for everyone — so sealed sections
  appear in every profile, which is why the read-only rule stays in the
  `dashboard` skill. Graduating the tool means adding the skill to
  `DEFAULT_SKILLS`.
