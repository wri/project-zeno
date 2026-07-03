# Dashboards MVP — frontend handoff

*Audience: the frontend build (separate repo, no access to this codebase).
This document is the narrative contract; the machine-readable truth is the
OpenAPI spec served by the backend at `/openapi.json` (interactive at
`/docs`). Backend lives on branch `feat/dashboards-mvp` of
`wri/project-zeno`. Design reference: the "Paraná, Brazil" dashboard mock
(2026-07).*

## What a dashboard is

A persistent, curated collection of **insight widgets for one area** (a
country, a state, a protected area) — a complement to the map explorer,
toggled in the top bar. Widgets *reference* insights that already exist;
nothing on a dashboard is recomputed when you view it. Dashboards are owned;
they can be made public.

**MVP scope cuts — do not build UI for these:** refresh / relative date
windows, subscribe-to-alerts, PDF export, multi-area (portfolio) dashboards.
The API enforces exactly one area per dashboard.

## Auth model (same as insights)

- All endpoints take the standard `Authorization: Bearer <token>`.
- Read: **own + public**. Write: **owner only**.
- `404` is returned for *both* "does not exist" and "exists but isn't
  yours" — do not distinguish them in UI.
- `401` on private resources when unauthenticated.

## REST API

Base path: `/api/dashboards`. Timestamps are ISO-8601 without timezone.

### Create — `POST /api/dashboards` (auth) → `201`

Exactly one AOI (2+ → `422`). `name` defaults to the AOI's name.

```json
// request
{
  "name": "Paraná",                       // optional
  "description": "Forest monitoring",     // optional
  "aois": [
    {
      "source": "gadm",                   // gadm | custom | wdpa | kba | landmark
      "src_id": "BRA.16_1",
      "subtype": "state-province",
      "name": "Paraná"
    }
  ]
}
```

```json
// response (DashboardResponse — the shape every dashboard endpoint returns)
{
  "id": "5c9f7dd8-…",
  "user_id": "user-abc",
  "name": "Paraná",
  "description": "Forest monitoring",
  "is_public": false,
  "created_at": "2026-07-03T14:05:22.123456",
  "updated_at": "2026-07-03T14:05:22.123456",
  "aois": [
    {
      "id": "a1b2…",
      "source": "gadm",
      "src_id": "BRA.16_1",
      "subtype": "state-province",
      "name": "Paraná",
      "position": 0
    }
  ],
  "widgets": []
}
```

### List — `GET /api/dashboards` (auth) → `200`

The caller's own dashboards, newest first: `[DashboardResponse, …]`.
Widgets in the *list* response are **not expanded** (`"insight": null`) —
use it for the dashboard switcher/overview, not for rendering widgets.

### Get one — `GET /api/dashboards/{id}` (auth optional) → `200 | 401 | 404`

The render endpoint. Public dashboards work without auth. Each widget is
expanded with its full insight payload:

```json
{
  "id": "5c9f7dd8-…",
  "…": "…dashboard fields as above…",
  "widgets": [
    {
      "id": "w-111…",
      "position": 0,
      "widget_type": "insight",
      "insight_id": "ins-222…",
      "config": { "default_view": "chart" },
      "created_at": "2026-07-03T14:10:00",
      "insight": {
        "id": "ins-222…",
        "user_id": "user-abc",
        "thread_id": "thread-1",
        "insight_text": "Tree cover loss in Paraná rose 12%…",
        "follow_up_suggestions": ["Compare to fires"],
        "statistics_ids": ["…"],
        "charts": [
          {
            "id": "c-333…",
            "position": 0,
            "title": "Annual tree cover loss",
            "chart_type": "bar",
            "x_axis": "year",
            "y_axis": "loss_ha",
            "color_field": "",
            "stack_field": "",
            "group_field": "",
            "series_fields": [],
            "chart_data": [{ "year": 2020, "loss_ha": 5 }]
          }
        ],
        "codeact_parts": [{ "type": "code", "content": "…base64…" }],
        "is_public": true,
        "created_at": "2026-07-01T09:00:00"
      }
    },
    {
      "id": "w-444…",
      "position": 1,
      "widget_type": "map",
      "insight_id": null,
      "config": { "…": "see dashboards-map-widgets-handoff.md" },
      "created_at": "2026-07-03T14:12:00",
      "insight": null
    }
  ]
}
```

**Key shortcut:** `widget.insight` is byte-for-byte the same shape as
`GET /api/insights/{id}` — reuse the existing insight-card component with no
new data mapping. The widget adds only `config` (presentation) on top.

`widget_type` is `"insight"` or `"map"`. Map widgets carry a self-contained
layer snapshot in `config` — the full contract (dataset layers, Sentinel-2
imagery, map focus, validation) lives in
**`dashboards-map-widgets-handoff.md`**.

An **insight widget with `"insight": null`** means the insight is not
visible to this viewer (e.g. it was made private again after the dashboard
was published). Render a placeholder ("not available"), not an error.

### Rename / description — `PATCH /api/dashboards/{id}` (owner) → `200`

Body: `{ "name": "…", "description": "…" }` (both optional). Returns the
dashboard.

### Publish — `PATCH /api/dashboards/{id}/public` (owner) → `200`

Body: `{ "is_public": true | false }`.

```json
// response = DashboardResponse plus:
{ "…": "…", "publicized_insight_ids": ["ins-222…"] }
```

**UX-critical:** publishing a dashboard **cascades `is_public: true` to
every insight its widgets reference** (otherwise a public dashboard renders
empty for viewers). Show a confirmation dialog before publishing, and use
`publicized_insight_ids` to tell the user which insights were made public.
**Unpublishing does NOT make those insights private again** — say so in the
unpublish confirmation.

### Widgets

- `POST /api/dashboards/{id}/widgets` (owner) → `201`. Body:
  `{ "widget_type": "insight", "insight_id": "…", "config": {…}, "position": 0 }`
  — `insight_id` required for insight widgets (`422` if missing; `404` if
  the caller can't see that insight); `position` defaults to the end.
  Returns the full dashboard **without** insight expansion — refetch
  `GET /api/dashboards/{id}` to render.
- `PATCH /api/dashboards/{id}/widgets/{widget_id}` (owner) → `200` —
  `{ "position": 2 }` and/or `{ "config": {…} }` (config is replaced whole,
  not merged). Reordering is per-widget; to reorder N widgets, send N
  PATCHes.
- `DELETE /api/dashboards/{id}/widgets/{widget_id}` (owner) → `204`. The
  referenced insight is untouched.

### Delete — `DELETE /api/dashboards/{id}` (owner) → `204`

Removes the dashboard and its widgets; insights survive.

### Two silent behaviors to design for

- If an **insight** is ever deleted (wherever that gets exposed), any
  widgets referencing it are silently deleted too, on every dashboard. No
  event is emitted — refetch on navigation rather than caching dashboards
  long-term.
- `config.default_view` (`"map" | "chart" | "table"`) is the widget's
  initial toggle state; `config.title` (optional) overrides the insight's
  title in the widget header.

## Chat / agent integration

The agent's dashboard tools (`create_dashboard`, `add_to_dashboard`,
`add_map_widget`) are in the **experimental profile** — send
`"ff": "experimental"` in the chat request for dashboard-aware chat.

**Outbound — tell the agent where the user is.** While on the dashboard
page, include in every chat request:

```json
{
  "query": "add this to my dashboard",
  "ff": "experimental",
  "view_context": {
    "page": "dashboard",
    "dashboard_id": "5c9f7dd8-…",
    "dashboard_name": "Paraná"
  }
}
```

This is what makes "add this to my dashboard" / "refine this dashboard"
work without the user naming anything: the backend renders a scope hint
from `page` + `dashboard_id` into the agent's context every turn, and
`add_to_dashboard` defaults to the dashboard on screen. `dashboard_name` is
optional but lets the agent name the dashboard without a DB read. On the
explorer, keep sending the existing `{"page": "map", …viewport/layers…}`.

**Inbound — react to agent writes.** Watch streamed tool messages for:

```json
{ "response_metadata": { "msg_type": "dashboard_updated", "dashboard_id": "5c9f7dd8-…" } }
```

On this signal, refetch `GET /api/dashboards/{dashboard_id}` — the agent
created the dashboard or added a widget. Same pattern as the existing
`insight_updated` handling (refetch-and-replace, not a new card).

**"Add to dashboard" toggle in the chat sidebar** (per the mock): every
analysis in chat has a persisted `insight_id` (already streamed in agent
state / `insight_updated` metadata). The toggle is a plain
`POST /api/dashboards/{id}/widgets` with that `insight_id` — no chat round
trip needed. Untoggling is `DELETE` on the widget.

## Suggested build order

1. Dashboard page shell + top-bar toggle; `GET` list + single; render
   widgets via the existing insight card (chart/table views come free,
   `default_view` from config).
2. Create flow (from the current explorer AOI) + rename + delete + widget
   remove/reorder.
3. Chat wiring: `view_context` outbound, `dashboard_updated` refetch,
   sidebar "Add to dashboard" toggle.
4. Publish/share flow with the cascade confirmation dialog.
5. Map widgets — see `dashboards-map-widgets-handoff.md` (self-contained
   configs, no layer resolution needed); insight widgets are the MVP core.
