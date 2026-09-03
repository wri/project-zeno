# Near-real-time monitoring sections (frontend handoff)

*Audience: the frontend build (separate repo, no access to this codebase).
This extends `dashboards-frontend-handoff.md` and
`dashboards-map-widgets-handoff.md`; everything there still holds.
Machine-readable truth: the OpenAPI spec at `/openapi.json`.*

## What this adds

One button that adds a **near-real-time (NRT) monitoring section** to a
dashboard. The section holds three widgets for the dashboard's area and one
date range:

| Position | `widget_type` | Content |
|---|---|---|
| 0 | `insight` | Line chart of alert area (ha) **per day**, by confidence tier |
| 1 | `map` | Integrated alerts tile layer for the same period |
| 2 | `map` | Sentinel-2 mosaic for the end of the same period |

The section's title and description are written by the backend from the
chart data. **The description is the summary** — it says what the section
shows and states the key figures. Render it as the section's body text, not
as a tooltip.

No new widget shapes: the `insight` widget and both `map` widgets use the
config contracts you already render.

## Sections now carry a type

Every section in `GET /api/dashboards/{id}` has a `type`:

```json
{
  "id": "sec-…",
  "title": "Recent disturbance in Paraná, last 2 weeks",
  "description": "1,240 ha of alerts, 62% high or highest confidence…",
  "position": 2,
  "type": "nrt-monitoring",
  "config": {
    "recipe": "nrt-monitoring",
    "days": 14,
    "start_date": "2026-08-20",
    "end_date": "2026-09-03"
  },
  "created_at": "2026-09-03T10:00:00"
}
```

`config` is how you show which period is on screen, and what to pre-select in
a window picker. **Read the period from here** — do not derive it from a
widget's tile layer. It is empty `{}` for a hand-composed section.

- `"default"` — a section composed widget by widget (all existing sections).
- `"nrt-monitoring"` — built by the recipe below, and **read-only**.

`POST …/sections` accepts an optional `type`, but only `"default"` is useful
there; a recipe section can only come from its own endpoint.

## The one call

```
POST /api/dashboards/{dashboard_id}/sections/nrt-monitoring
```

Owner only. An empty body `{}` works — every field has a default:

| Field | Default | Notes |
|---|---|---|
| `days` | **14** | Length of the alert window, counted back from today (1–365) |
| `window_days` | 7 | Imagery search window, ±N days around the period end (1–183) |
| `max_cloud_cover` | 20 | Imagery cloud limit, percent (0–100) |
| `title` | null | Overrides the generated title |
| `description` | null | Overrides the generated description |
| `force` | false | Build even if a section for this period exists |

**This is a synchronous call and it is slow** — it pulls alert data, searches
for satellite scenes, builds a mosaic and writes the summary before it
answers. Budget tens of seconds, set your client timeout accordingly, and
show a progress state. There is no job to poll.

`201` returns the **whole dashboard** (same shape as
`GET /api/dashboards/{id}`, insight payloads expanded) plus three fields:

```json
{
  "id": "dash-…",
  "sections": [ … ],
  "widgets": [ … ],
  "section_id": "sec-…",
  "created": true,
  "warnings": []
}
```

- `section_id` — the section that was created; use it to scroll to it.
- `created` — `false` when an existing section for the same period was
  returned instead of building a new one (see *Double clicks*).
- `days`, `start_date`, `end_date` — the window the section now covers.
- `warnings` — human-readable reasons a widget is missing.

You do not need to refetch the dashboard: render the response.

### Failure and degradation

| Status | Meaning | What to show |
|---|---|---|
| `201`, `warnings: []` | Three widgets | The section |
| `201`, `warnings: [...]` | **Two** widgets, no imagery | The section, plus the warning |
| `422` | Dashboard has no area, or a field is out of range | The validation message |
| `404` | Not your dashboard, or it does not exist | Not found |
| `409` | — | Only from writes *to* a sealed section, never from this call |
| `502` | Alert data could not be pulled | Retry is reasonable |

**Do not assume three widgets.** Satellite imagery is best-effort: areas over
the mosaic size limit (50,000 km², so country-level dashboards) and periods
with no cloud-free scenes yield a two-widget section, with the reason in
`warnings`. The section is still useful. Read the widget list, not a fixed
layout.

### Double clicks

Called twice for the same period, the second call builds nothing and returns
the existing section with `created: false`. Each build costs a data pull, a
scene search and a model call, so leave the guard on; pass `force: true` only
for an explicit "build another".

## Changing the window

```
POST /api/dashboards/{dashboard_id}/sections/{section_id}/refresh
```

The one-click way to move a monitoring section to a different period. Body is
the same three fields, all optional: `days` (default 14), `window_days`,
`max_cloud_cover`.

Everything the section shows moves together — the chart is recomputed, the
alerts layer re-cut to the new dates, the imagery rebuilt for the new period
end, and the title and description rewritten, since they state the period.
**The section keeps its id and its place on the dashboard**, so a link to it
still resolves and you can refresh in place rather than re-rendering the page.

Returns `200` with the same body as the build (`created: false`). Same timing
— tens of seconds, synchronous — and the same degradation rules: imagery may
be missing with a reason in `warnings`.

- `422` if the section is not `nrt-monitoring` (a hand-composed section has
  no recipe to re-run), or `days` is out of range.
- `404` if the section is not on that dashboard, or the dashboard is not the
  caller's.
- `502` if the alert data could not be pulled — the section is left as it was.

**The previous chart insight is deleted** once nothing points at it. It was
that section's own content, for a period the section no longer covers. So do
not keep an insight id from before a refresh and expect it to resolve.

Sensible windows to offer: 14 days (the default), 30, 90. Pre-select the
current one from `section.config.days`.

## The section is read-only

An `nrt-monitoring` section is a record of one build — one area, one period,
the data as it was — so changing its **content** would make its own title and
description untrue. **Hide these affordances inside it**: rename, edit
description, add widget, delete a single widget, move a widget in or out, and
any per-widget config editor.

**Layout is deliberately still editable.** Rearranging and resizing what a
recipe built changes how the section looks, not what it says, so **keep your
drag-to-reorder and single/double controls working inside these sections** —
they need no special handling:

- `PATCH …/widgets/{widget_id}` with `position` — allowed.
- The same call replacing `config`, where the only keys whose values differ
  are `size` and `sizes` — allowed.
- Any other config difference, or a `section_id` move — `409`.

The config rule is a **diff**, not a field whitelist, because `PATCH`
replaces config wholesale: "resize it" and "resize it and swap its
`tile_url`" arrive as the same shape of request, and only the diff tells them
apart. Send the config you were given with `size` changed and nothing else,
which is what your existing resize already does.

Also still available:

- **Delete the whole section** — `DELETE …/sections/{section_id}`. This
  always removes the section's widgets, whatever `delete_widgets` says (for
  a `default` section, that flag still behaves as documented).
- **Reorder the section** among the other sections — `PATCH
  …/sections/{section_id}` with `position` only.
- Publishing the dashboard, which cascades to the section's insight as usual.

Every blocked write answers `409` with

```json
{ "detail": "Section is read-only (type: nrt-monitoring)" }
```

That covers `PATCH …/sections/{id}` with a title or description, `POST
…/widgets` with the section's `section_id`, `PATCH …/widgets/{id}` carrying a
content-changing `config` or a move, moving an outside widget *into* it, and `DELETE
…/widgets/{id}` inside it. Treat a `409` as a bug in your own UI state rather
than something to surface raw: the controls should not have been offered.

To change what a monitoring section shows, delete it and build a new one.

## Chat

The agent can do the same thing when asked to monitor an area
(`add_nrt_monitoring_section`). Nothing new to wire — it emits the signal you
already handle:

```json
{ "response_metadata": { "msg_type": "dashboard_updated", "dashboard_id": "…" } }
```

→ refetch `GET /api/dashboards/{dashboard_id}` and re-render.

## Widget config keys, for the record

`config` was never validated on `PATCH`, so the frontend has been persisting
keys the backend documented nowhere. Found in the wild: `size`
(`"single"`/`"double"`), `sizes` (per-chart map), `chartIds`, `summaryHidden`,
alongside the documented `default_view`, `title`, `dataset`, `imagery` and
`text`. Nothing about that changes here and no migration touches them — but
`size` and `sizes` are now **named in the backend** as the layout keys, since
the seal has to tell layout from content. If you rename them or add another
layout key, that list has to move with you:
`dashboard_writer.LAYOUT_CONFIG_KEYS`.

## Also new: mosaic tile URLs

`POST /mosaic/create/{source}/{src_id}` now returns `tile_url` and
`tilejson_url` alongside `mosaic_id`, so imagery can be rendered (and an
imagery map widget built) without deriving the URL yourself. Additive — no
existing field changed.

## Not in scope

No refresh-in-place (delete and rebuild), no relative/rolling date windows,
no subscribe-to-alerts, no viewport editing, single-area dashboards only.
