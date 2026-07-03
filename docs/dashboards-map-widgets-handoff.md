# Dashboards — map widgets (frontend handoff, extension)

*Audience: the frontend build (separate repo, no access to this codebase).
This extends the dashboards MVP handoff (`dashboards-frontend-handoff.md`);
everything there still holds — this doc only covers what map widgets add.
Machine-readable truth: the OpenAPI spec at `/openapi.json`. Backend lives on
branch `feat/dashboards-mvp` of `wri/project-zeno`.*

## What changed

Map widgets (`widget_type: "map"`) are now real. The agent can create them
(new `add_map_widget` tool), and the API validates their config. The
speculative config shape in the MVP handoff (flat `dataset_id` /
`start_date` keys) is **replaced** by the contract below.

There are two kinds of map widget, discriminated by exactly one of two keys
in `config`:

- **`config.dataset`** — a dataset rendered as a tile layer (e.g. tree
  cover loss over Paraná).
- **`config.imagery`** — a Sentinel-2 satellite mosaic the agent built.

Both are **self-contained snapshots**: render `tile_url` directly. No layer
resolution, no catalog lookup, no chat state needed. The sub-objects mirror
the `dataset` / `imagery` agent-state updates the explorer already renders —
reuse that layer-rendering code.

## Config shapes

### Dataset map widget

```json
{
  "id": "w-444…",
  "position": 1,
  "widget_type": "map",
  "insight_id": null,
  "insight": null,
  "config": {
    "default_view": "map",
    "title": "Tree cover loss",              // optional header override
    "dataset": {
      "dataset_id": 4,
      "dataset_name": "Tree cover loss",
      "tile_url": "https://tiles.globalforestwatch.org/…/{z}/{x}/{y}.png?…",
      "context_layer": "driver",             // chosen context layer, or null
      "context_layers": [                    // all available context layers
        { "name": "driver", "tile_url": "https://…/{z}/{x}/{y}.png" }
      ],
      "parameters": [                        // dataset params, or null
        { "name": "canopy_cover", "values": [30] }
      ],
      "start_date": "2024-01-01",            // nullable
      "end_date": "2024-12-31"               // nullable
    }
  }
}
```

`tile_url` is fully resolved (thresholds/params baked in) — the same URL the
explorer renders when this dataset is selected in chat. `context_layer` names
which entry of `context_layers` is active; render it like the explorer does.

### Imagery map widget

```json
{
  "widget_type": "map",
  "insight_id": null,
  "insight": null,
  "config": {
    "default_view": "map",
    "title": "Sentinel-2, June 2024",        // optional
    "imagery": {
      "tile_url": "https://tiles.globalforestwatch.org/cog/mosaic/tiles/WebMercatorQuad/{z}/{x}/{y}.png?url=…",
      "tilejson_url": "https://tiles.globalforestwatch.org/cog/mosaic/WebMercatorQuad/tilejson.json?url=…",
      "mosaic_id": "eyJhIjp…",
      "item_count": 12,                       // null on mosaic-cache hit
      "date_start": "2024-05-28",             // null on mosaic-cache hit
      "date_end": "2024-06-04",               // null on mosaic-cache hit
      "target_date": "2024-06-01",
      "window_days": 7,
      "max_cloud_cover": 20,
      "aoi_names": ["Paraná"]
    }
  }
}
```

Identical to the `imagery` state update from the chat `show_imagery` flow.
The tile URLs are stable and content-addressed (the mosaic persists in S3);
`mosaic_id` is the durable reference — ignore it for rendering, but keep it
in any config you write back. Note the mosaic only has tiles where it was
built (its own area); outside that, tiles are empty.

## Map focus

**Map widgets render fitted to the dashboard's area by default.** Get the
geometry from the dashboard's `aois` via the existing
`GET /api/geometry/{source}/{src_id}` and fit the viewport to it (same
mechanism as the explorer AOI fit). `config.viewport` is a reserved manual
override the backend never writes — if present, it wins; do not build UI to
set it.

## Creating map widgets over REST

`POST /api/dashboards/{id}/widgets` (owner) with `widget_type: "map"` now
validates `config`, returning `422` when:

- `config` is missing, or
- it contains **neither or both** of `dataset` / `imagery`, or
- the present sub-object has no non-empty `tile_url`.

Nothing else inside the sub-object is validated — extra keys are fine.
Insight widgets are unchanged. `PATCH …/widgets/{widget_id}` still replaces
`config` whole and is **not** re-validated (owner-only endpoint) — send back
the full config when patching.

## Chat / agent integration

Nothing new to wire. The agent's new `add_map_widget` tool (experimental
profile, like the other dashboard tools) emits the same signal you already
handle:

```json
{ "response_metadata": { "msg_type": "dashboard_updated", "dashboard_id": "…" } }
```

→ refetch `GET /api/dashboards/{dashboard_id}` and re-render. Users can now
say "add this layer to my dashboard" (after a dataset was picked in chat) or
"add the imagery to my dashboard" (after satellite imagery was shown).

## Scope cuts (unchanged from MVP)

No refresh/relative date windows, no viewport-editing UI, no
subscribe-to-alerts, no PDF export, single-area only.
