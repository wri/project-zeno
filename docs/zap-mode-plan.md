# Zap mode plan: extraction, history, undo and dashboards

Status: proposal. Phase 1 (the map eval and its baseline) and phase 2
(Clairic extraction and the full current state) are done. Phase 3 is on a
frontend branch. The backend parts of phase 4 (the dashboard planner, tier
1 additions) and phase 5 (layout edits and tier 2 edits) are done: see
"8. Dashboard step contract", "Phase 4 result" and "Phase 5 result". The
other phases have no code.

## Goal

Zap mode changes the map from one request, with no agent and no text
generation. This plan extends it in four directions:

1. Read the place, the time and the numbers of a request with the Clairic
   extraction model. Keep jev for the decisions.
2. Keep a history of the requests in the browser. The history is a list of
   states, not a conversation.
3. Add an undo button on the map.
4. Let zap edit dashboards, with a confirmation for edits that are not
   clear or not safe.

Not in this plan: undo for dashboard edits. To take back a dashboard edit,
the user makes a new request, for example "remove that chart". A real undo
can come later.

## Review of zap mode today

Backend (`src/api/services/zap/`, PR #850): `POST /api/zap` is for admins
only. It gets the prompt and the current dataset and area. It makes two jev
calls and returns a plan of up to three steps: show a dataset, go to an
area, chart the dataset for the area. It changes nothing on the server.

Frontend (`wri/project-zeno-next`, branch `feat/zap-mode`, flag `ff=zap`):
`runZap` runs the steps in order. `ZapPanel` shows the steps and the jev
decisions. The store holds one plan. A new request replaces it.

Limits that this plan removes:

| Limit | Cause | Example that fails |
|---|---|---|
| A place of more than four words loses words | The place is an option list of 1 to 4 word spans (`place_spans`) | "Ciudad Autónoma de Buenos Aires" |
| No free date range | The period is an option list: a year, "since a year", three relative periods | "from 2015 to 2020", "alerts in March 2026", "the last 3 months" |
| A weak period answer is dropped | `PERIOD_THRESHOLD = 0.35` | "recent" splits between two options |
| A follow-up request loses the forest type and the canopy cover | `ZapCurrent` has only `dataset_id` and `area`. The planner builds the dataset again with no context layer | "primary forest loss in Pará", then "since 2015" |
| No history, no undo | The endpoint has no state, and the store holds one plan | |
| Map only | `useZapMode` is off on `/dashboards/*`, and no step kind writes a dashboard | |
| The chart step cannot select a chart | The step runs `/api/analyze`, which builds the default charts of the dataset | |
| No eval | The tests mock jev. No labelled set measures the plan quality | |

Limits that stay: one area for each request, English place names (this is a
limit of `search_aois`, not of the model), datasets 9 and 12 not offered.

## Design

### 1. Clairic for values, jev for decisions

The stac-zap tests of 2026-11-12 (`stac-zap/docs/decision-models.md`, Test
3) give the method. Clairic was correct on 84 of 85 values and on 16 of 16
requests that option lists cannot hold. jev was correct on 80 of 85 and 0
of 16. The cost increased from $0.00042 to $0.00050 for each request.

Clairic is on the OpenRouter extractions API (`/api/alpha/extractions`,
model `cloudflare/clairic`). It uses the `OPENROUTER_API_KEY` that zap has
now. No new credential is necessary.

New module `src/api/services/zap/extract.py`, a port of
`stac-zap/src/zap/extract.ts`:

| Call | State | Fields | Replaces |
|---|---|---|---|
| A | The request only | `place` (text), `canopy` (number, percent), `cloud` (number, percent), `title` (text) | The `place` question, the `canopy` question |
| B | The app context, today's date and the request | `when` (text), `start` (date), `end` (date) | The `period` question |

Rules from the stac-zap tests that the port keeps:

- The time fields go in their own call. In one call, a number such as "12%
  clouds" moved into the dates.
- Only the time call gets the app context. The place and the numbers were
  better with the request only.
- `when` tells if the request names a time. With today's date in the
  state, the model gives a range for each request.
- Code does the calendar. A season, a quarter, "the last 3 months" and
  "recent" get their range from code, from the words in `when`.

Rules that are new for Zeno:

- `revise_date_range` clamps the range to the dataset, as it does now.
- `canopy` snaps to the nearest value that the dataset permits. A value
  that is more than 5 points from a permitted value adds a note.
- `cloud` is only for imagery (see "Dashboard actions").
- `title` holds the words of the user for a name or a note, for example
  "rename the section to Fire season". Zap does not write text itself.

jev keeps these questions: `dataset`, `scope`, the `area` from the
`search_aois` results, `context`, and the new `action`, `target` and
`view` questions (see below).

Sequence for one request: calls A and B and the first jev call start at the
same time. Then `search_aois` runs on the place. Then the second jev call
selects the area and the dataset options. The total time stays near 1 s.

Fallback: when Clairic does not answer, the planner asks the `place`,
`period` and `canopy` questions of today. The extractions API is an alpha
release and Clairic is a preview model, so the old questions stay in the
code.

### 2. The full current state

`ZapCurrent` gets the dates, the context layer, the canopy cover, the page
(`map` or `dashboard`) and the dashboard id. The planner starts from this
state and changes only what the request names. This repairs the follow-up
defect in the table above. It is also the base of the history.

`ZapPlan` gets a `state` field: the state after the plan. The frontend
stores it and sends it back as `current` with the next request.

### 3. History

The history is a trail of states. Each entry has the prompt, the plan and
the state after it. It shows as a short list of rows:

```
⚡ Deforestation in Pará            Tree cover loss · Pará · 2001–2025
⚡ since 2015, primary forest       Tree cover loss · Pará · 2015–2025 · primary
⚡ fires instead                    Loss due to fires · Pará · 2015–2025     ← now
```

- A row is the prompt and the result as chips. It has no answer text and
  no speaker.
- A click on a row puts the map in that state.
- A new request applies to the state of the selected row. If the row is
  not the last row, the later rows are removed, as in browser history.
- A chip can open the other options of its decision. jev returns a
  probability for each option, so the plan can carry the top three. One
  click corrects a wrong dataset or area with no new request.

Storage: the trail is in the browser only (session storage). The backend
stores nothing. There is one trail for the map and one for each dashboard.
A trail keeps the last 20 rows. When a row is added to a full trail, the
oldest row is removed. A trail ends when the browser tab closes.

On a dashboard, a row is a record of what the request did. It shows the
prompt and the edit, for example "Added: Tree cover loss per year". A row
cannot put the dashboard back in an earlier state, so a click on it does
nothing more than show its decisions.

### 4. Undo

Undo is for the map only. Undo selects the row before the current row.
Redo selects the row after it. No server call is necessary, because a map
row holds the full state.

A dashboard has no undo button. A dashboard edit is in the database, and a
correct undo needs a stored snapshot or inverse operations. This plan does
not include that. The user takes back an edit with a new request or with
the page controls. Because of this:

- A removal always gets a confirmation (see "Tiers and confirmation").
- A removed widget does not delete its insight, so "add the tree cover loss
  chart again" can bring it back.
- The row of the last edit names the widget or the section, so a follow-up
  request such as "remove that" has a clear target. The planner gets the
  ids of the last edit in `current`, and the `target` question lists them
  first.

### 5. Zap on a dashboard

On a dashboard page, the first jev call gets an `action` question. The
area is the area of the dashboard, so the `place` field is not used.

| Action | What zap does | Tier |
|---|---|---|
| `add_chart` | Runs `/api/analyze` for the dataset and the period, then adds the insight as a widget | 1 |
| `add_map` | Adds a map widget for the dataset (`widget_configs.dataset_config`) | 1 |
| `add_template` | Applies an analysis template. jev selects one of the three templates | 1 |
| `add_imagery` | Adds a Sentinel-2 imagery widget. The date and `cloud` come from Clairic | 1 |
| `add_section` | Adds an empty section. The title is the `title` field | 1 |
| `move` | Moves a widget to a section or to the top level | 1 |
| `resize` | Sets a widget to half width or full width | 1 |
| `rename` | Changes the name of the dashboard or the title of a section to the `title` field | 1 |
| `change_period` | Builds one chart widget again for a new period and replaces it | 2 |
| `remove` | Removes a widget, or a section with or without its widgets | 2 |
| `none` | Changes nothing | |

The `target` question: for `move`, `resize`, `rename`, `change_period` and
`remove`, the second jev call selects the widget or the section. The options
are the titles of the widgets and the sections of the dashboard, and "none
of these". jev selected correctly from up to 250 options in the stac-zap
tests, and a dashboard has fewer.

The `view` question: when the dataset has more than one view in
`src/api/services/charts/views.py`, jev selects the view for `add_chart`.
This needs the view registry of the low AI mode plan (phase 1, not merged).

### 6. Tiers and confirmation

| Tier | Edits | Behaviour |
|---|---|---|
| 0 | Map changes | Applied immediately. Undo is local |
| 1 | Additions and layout changes on a dashboard | Applied immediately, if each decision is clear. No undo: a new request or the page controls take the edit back |
| 2 | Removals, replacements, an edit of more than one widget, and each tier 1 edit with a decision that is not clear | The plan shows as a preview. The user confirms or corrects it |
| 3 | Delete a dashboard, publish a dashboard, more than one area | Not in zap. A note sends the user to the page controls or to the assistant |

A decision is clear when the probability of the selected option is at
least 0.7 and at least 0.25 above the second option. For a Clairic field,
`p_null` must be below 0.2 or above 0.8. The first value of the minimum
probability was 0.6. The dashboard dev part changed it to 0.7 (see "Phase
4 result"). All the numbers are in `src/api/services/zap/tiers.py`.

A confirmation is not only "yes" or "no". The preview shows the decision
that is not clear with its top options as chips, for example "Which
widget? [Tree cover loss per year] [Tree cover loss by driver]". One click
selects the option and applies the edit.

Publish is in tier 3 because it also makes the insights of the dashboard
public, and nothing can take that back for a person who already has the
link.

### 7. API

`POST /api/zap` stays the only zap endpoint, and it stays a planner. It
gets the full `current` and returns the steps, the decisions with their top
options, the `state`, a `tier` and `needs_confirmation`. It changes
nothing and stores nothing.

The frontend runs all steps, as it does for the map today. A dashboard
step uses the dashboard endpoints that exist:

| Step | Endpoint |
|---|---|
| `add_chart` | `POST /api/analyze`, then `POST /api/dashboards/{id}/widgets` with the insight |
| `add_map` | `POST /api/dashboards/{id}/widgets`. The plan step holds the widget config |
| `add_imagery` | `POST /mosaic/create/{source}/{src_id}`, then `POST /api/dashboards/{id}/widgets`. The plan step holds the widget config |
| `add_template` | `POST /api/dashboards/{id}/sections/from-template` |
| `add_section` | `POST /api/dashboards/{id}/sections` |
| `move`, `resize` | `PATCH /api/dashboards/{id}/widgets/{widget_id}` |
| `rename` | `PATCH /api/dashboards/{id}` or `PATCH .../sections/{section_id}` |
| `change_period` | `POST /api/analyze`, add the new widget at the position of the old widget, then remove the old widget |
| `remove` | `DELETE .../widgets/{widget_id}` or `DELETE .../sections/{section_id}` |

These endpoints are for the owner only, so zap needs no new access rule
and no new table. A plan with more than one step is not one transaction. If
a step fails, the steps before it stay, and the trail row shows which step
failed.

### 8. Dashboard step contract

This section is the contract between the dashboard planner (phases 4 and
5, backend) and the frontend that runs the steps. The models are in
`src/api/services/zap/models.py`. All the new fields are optional, so the
map client of phases 2 and 3 continues to work with no change. Phase 5
added the fields `last_widget_ids`, `last_section_ids` and `choose`, the
decision fields `key` and `value`, and the edit steps (from
"**`add_section`**" below).

#### Request

`POST /api/zap` with `current.page` set to `"dashboard"` and
`current.dashboard_id` set to the id of the open dashboard:

```json
{
  "prompt": "add a chart of tree cover loss since 2015",
  "current": {
    "page": "dashboard",
    "dashboard_id": "5b0c4f9e-...",
    "dataset_id": 4,
    "start_date": "2015-01-01",
    "end_date": "2025-12-31",
    "context_layer": "primary_forest",
    "canopy_cover": null
  }
}
```

- `page`: `"map"`, `"dashboard"` or absent. Absent is the map.
- `dashboard_id`: necessary when `page` is `"dashboard"`.
- The other fields are optional. On a dashboard, they are the data of the
  last addition: send back `plan.state` of the last plan on the same
  dashboard. Then "and a map of it" adds the same data. Do not send the
  `area`: the planner always uses the first area of the dashboard.
- `last_widget_ids` and `last_section_ids` (phase 5): the ids of the
  widgets and the sections that the last plan on this dashboard added or
  changed. The `target` question lists these items first and marks them,
  so "remove that" or "make it full width" selects them. After the steps
  run, set them in the state from the responses of the endpoints: the new
  widget of `add_chart`, `add_map`, `add_imagery` and `change_period`, the
  new section of `add_section`, and the new section and its widgets of
  `add_template`. For `move`, `resize` and `rename` of a section, the
  planner sets them in `plan.state`. After `remove`, they are null.

`choose` (phase 5, optional) is next to `prompt` and `current`. It holds
the options that the user selected, as `{decision key: option value}`, for
example `{"target": "widget:5c1d..."}`. The planner uses these options in
place of the jev answers. Use it for a chip of a tier 2 preview: send the
same prompt and `current` again, with the `key` of the decision and the
`value` of the option of the chip. A value that is not an option of the
question has no effect.

The planner reads the dashboard from the database. If the dashboard does
not exist or the user is not its owner, the plan has no steps and one note.
An admin gets no steps on the dashboard of another user.

#### Plan

| Field | Content |
|---|---|
| `steps` | Zero or one step on a dashboard. |
| `decisions` | The decisions, as on the map. Each jev decision has `options` (up to three other options, best first, with no "keep" and no "none" option) and `clear`. A Clairic or code decision has `clear` and no `options`. On a dashboard, the jev decisions also have `key` (the decision key for `choose`) and `value` (the id of the selected option), and each option has a `value`. A decision from `choose` has `source: "user"`. |
| `notes` | A note when the plan has no steps, or when a value changed (for example a canopy cover of 12% becomes 10%). Show the notes to the user. |
| `state` | The state to send as `current` with the next request on this dashboard. It has the page, the dashboard id, the area of the dashboard, the data of the last addition or new period, and the last-edit ids that the planner knows. |
| `tier` | 1: apply the steps immediately. 2: show the plan as a preview, and apply it only after the user confirms. Null when there are no steps. A map plan with steps has tier 0. |
| `needs_confirmation` | True for tier 2. On the map, false. |

The tier of a dashboard plan (`src/api/services/zap/tiers.py`):

- `change_period` and `remove` are always tier 2.
- A plan that changes more than one widget that exists is tier 2: the
  removal of a section with its widgets, when the section has two or more
  widgets.
- Each other plan is tier 1 when all its decisions are clear, else tier 2.

A decision option is `{"label": "...", "probability": 0.15}`. The label of
a dataset option is the dataset name, and the label of an area option is
the area name. A selected option can go back to the planner as a new
request, as in phase 3.

For a tier 2 plan, the decisions with `clear: false` are the decisions to
show with their `options`. A `change_period` or `remove` plan can be tier 2
with all its decisions clear: then show the step and a confirm button. The
`target` decision always carries the next targets in its `options`, so the
preview can ask "Which widget?" with chips. A chip sends `choose` (see
"Request"). The new plan of a `remove` or `change_period` is tier 2 again:
show it again for the confirmation.

#### Steps

Each step has `kind`, `title`, `detail` and `args`. `title` and `detail`
are short texts for the plan panel and the trail row. The frontend runs the
step with `args` only. It needs no catalog lookup and no dashboard lookup.
An edit step names its target in `title` and with a label in `args`
(`widget_label` or `label`), for example
`Chart "Tree cover loss per year" in section "Overview"`.

**`add_chart`**: a chart of one dataset for the area of the dashboard.

```json
{
  "kind": "add_chart",
  "title": "Add chart: Tree cover loss",
  "detail": "2015–2025 · primary forest · Pará, Brazil",
  "args": {
    "dashboard_id": "5b0c4f9e-...",
    "dataset_name": "Tree cover loss",
    "analyze": {
      "aois": [{"source": "gadm", "src_id": "BRA.14_1", "subtype": "state-province"}],
      "dataset_id": 4,
      "start_date": "2015-01-01",
      "end_date": "2025-12-31",
      "context_layer": "primary_forest",
      "canopy_cover": null
    },
    "widget": {"widget_type": "insight", "insight_id": null, "config": {"default_view": "chart"}}
  }
}
```

1. Send `args.analyze` as the body of `POST /api/analyze`. Do not send a
   `thread_id`.
2. Poll `GET /api/jobs/{id}` until the job is `completed` or `failed`, as
   `ZapRunner` does for the map chart step.
3. Get the insight id from the `resource_url` of the job resource
   (`/api/insights/{id}`).
4. Set `args.widget.insight_id` to the insight id. Send `args.widget` as
   the body of `POST /api/dashboards/{dashboard_id}/widgets`.

The dates are already in the range of the dataset.

**`add_map`**: a map layer of one dataset.

```json
{
  "kind": "add_map",
  "title": "Add map: Tree cover loss due to fires",
  "detail": "2001–2025 · Pará, Brazil",
  "args": {
    "dashboard_id": "5b0c4f9e-...",
    "dataset_name": "Tree cover loss due to fires",
    "widget": {
      "widget_type": "map",
      "insight_id": null,
      "config": {
        "default_view": "map",
        "dataset": {"dataset_id": 10, "dataset_name": "...", "tile_url": "...", "context_layer": null, "selected_layer": null, "context_layers": [], "parameters": null, "layers": null, "start_date": "2001-01-01", "end_date": "2025-12-31"}
      }
    }
  }
}
```

Send `args.widget` as the body of
`POST /api/dashboards/{dashboard_id}/widgets`. `config.dataset` is the
snapshot of `widget_configs.dataset_config`, the same snapshot that the
`add_map_widget` tool and the analysis templates write.

**`add_template`**: a section from an analysis template.

```json
{
  "kind": "add_template",
  "title": "Add section: Tree cover loss and its drivers",
  "detail": "the loss each year since 2001, its causes, and a map of the drivers",
  "args": {"dashboard_id": "5b0c4f9e-...", "template": "forest-loss-drivers", "args": {}}
}
```

Send `{"template": args.template, "args": args.args}` as the body of
`POST /api/dashboards/{dashboard_id}/sections/from-template`. The request
takes tens of seconds. The response has the new section, its widgets and
`warnings`. Show the warnings. The templates are `nrt-monitoring`,
`post-2020-forest-loss` and `forest-loss-drivers`.

**`add_imagery`**: a Sentinel-2 imagery map.

```json
{
  "kind": "add_imagery",
  "title": "Add imagery: Sentinel-2",
  "detail": "around 2025-03-16 · ±15 days · ≤10% clouds · Pará, Brazil",
  "args": {
    "dashboard_id": "5b0c4f9e-...",
    "mosaic": {"source": "gadm", "src_id": "BRA.14_1", "target_date": "2025-03-16", "window_days": 15, "max_cloud_cover": 10, "max_items": 50},
    "widget": {
      "widget_type": "map",
      "insight_id": null,
      "config": {
        "default_view": "map",
        "imagery": {"provider": "sentinel-2", "tile_url": "...", "tilejson_url": "...", "mosaic_id": "eyJh...", "target_date": "2025-03-16", "window_days": 15, "max_cloud_cover": 10, "aoi_names": ["Pará, Brazil"]}
      }
    }
  }
}
```

1. Send `POST /mosaic/create/{mosaic.source}/{mosaic.src_id}` with the
   query `target_date`, `window_days`, `max_cloud_cover` and `max_items`
   from `args.mosaic`. This builds the mosaic.
2. If the call fails (404: no scenes, 422: the area is too large), stop
   the step and show the error. Do not add the widget.
3. Add the statistics of the response to `args.widget.config.imagery`:
   `item_count`, `start_date` (from `date_start`), `end_date` (from
   `date_end`), `mean_cloud_cover`, `min_cloud_cover` and
   `max_cloud_cover_observed` (from `max_cloud_cover`).
4. Send `args.widget` as the body of
   `POST /api/dashboards/{dashboard_id}/widgets`.

The planner computes `mosaic_id`, `tile_url` and `tilejson_url` from the
same recipe as the mosaic service. Thus the `mosaic_id` of the response
is the same as `config.imagery.mosaic_id`. If it is different, the tile
URLs in the config are wrong: stop the step and do not add the widget.

The imagery dates: with no time in the request, the target date is today
and the window is 30 days. For a period that runs to today ("recent",
"the last 2 weeks"), the target date is today and the window is the length
of the period, from 7 to 30 days. For a period in the past, the target date
is the middle day and the window is half the period, from 7 to 183 days.
The maximum cloud cover is the `cloud` value of Clairic, else 20.

**`add_section`** (phase 5): an empty section. The title is the words of
the user, from the Clairic `title` field.

```json
{
  "kind": "add_section",
  "title": "Add section: \"Fire season\"",
  "detail": "an empty section",
  "args": {"dashboard_id": "5b0c4f9e-...", "section": {"title": "Fire season"}}
}
```

Send `args.section` as the body of
`POST /api/dashboards/{dashboard_id}/sections`. Set `last_section_ids` to
the id of the new section.

**`move`** (phase 5): a widget into a section, or out of its section to the
top level.

```json
{
  "kind": "move",
  "title": "Move: Map \"Tree cover loss\"",
  "detail": "to section \"Drivers\"",
  "args": {
    "dashboard_id": "5b0c4f9e-...",
    "widget_id": "8a1e...",
    "widget_label": "Map \"Tree cover loss\" at the top level",
    "destination_label": "section \"Drivers\"",
    "patch": {"section_id": "77c0..."}
  }
}
```

Send `args.patch` as the body of
`PATCH /api/dashboards/{dashboard_id}/widgets/{widget_id}`. A move to the
top level has `"patch": {"section_id": null}`. Keep the null in the body:
the endpoint reads a missing `section_id` as "no change". The widget goes
to the end of its new container.

**`resize`** (phase 5): a widget at half width (`single`) or full width
(`double`).

```json
{
  "kind": "resize",
  "title": "Resize: Chart \"Tree cover loss by driver\"",
  "detail": "full width (was half width)",
  "args": {
    "dashboard_id": "5b0c4f9e-...",
    "widget_id": "8a1e...",
    "widget_label": "Chart \"Tree cover loss by driver\" in section \"Drivers\"",
    "size": "double",
    "patch": {"config": {"default_view": "chart", "size": "double"}}
  }
}
```

Send `args.patch` as the body of
`PATCH /api/dashboards/{dashboard_id}/widgets/{widget_id}`. The endpoint
replaces the config, so `patch.config` is the full config of the widget
with the new `size`. A widget with no `size` in its config is full width
for a chart, a map and an alerts list, and half width for the other types
(the rule of `topLevelWidgetSize` in the frontend).

**`rename`** (phase 5): the name of the dashboard or the title of a
section. The new name is the words of the user.

```json
{
  "kind": "rename",
  "title": "Rename section: \"Fires\"",
  "detail": "to \"Fire season\"",
  "args": {
    "dashboard_id": "5b0c4f9e-...",
    "target_type": "section",
    "section_id": "77c0...",
    "old_title": "Fires",
    "title": "Fire season",
    "patch": {"title": "Fire season"}
  }
}
```

For `target_type` `"section"`, send `args.patch` as the body of
`PATCH /api/dashboards/{dashboard_id}/sections/{section_id}`. For
`"dashboard"`, `section_id` is null and `patch` is `{"name": "..."}`: send
it as the body of `PATCH /api/dashboards/{dashboard_id}`.

**`change_period`** (phase 5, always tier 2): one chart or one dataset map
for a new period, in the place of the old widget.

```json
{
  "kind": "change_period",
  "title": "New period: Chart \"Tree cover loss per year\"",
  "detail": "2015–2020 (was 2001–2025) · replaces the widget",
  "args": {
    "dashboard_id": "5b0c4f9e-...",
    "widget_id": "8a1e...",
    "widget_label": "Chart \"Tree cover loss per year\" in section \"Overview\"",
    "dataset_name": "Tree cover loss",
    "old_start_date": "2001-01-01",
    "old_end_date": "2025-12-31",
    "replace": true,
    "analyze": {
      "aois": [{"source": "gadm", "src_id": "BRA.14_1", "subtype": "state-province"}],
      "dataset_id": 4,
      "start_date": "2015-01-01",
      "end_date": "2020-12-31",
      "context_layer": "primary_forest",
      "canopy_cover": 30
    },
    "widget": {
      "widget_type": "insight",
      "insight_id": null,
      "config": {"default_view": "chart", "size": "single"},
      "position": 0,
      "section_id": "77c0..."
    }
  }
}
```

1. If `args.analyze` is set (a chart), run it as for `add_chart`: send it
   to `POST /api/analyze`, wait for the job, and set
   `args.widget.insight_id` to the new insight id. For a map, `analyze` is
   null and `args.widget.config.dataset` is the new map layer.
2. Send `args.widget` as the body of
   `POST /api/dashboards/{dashboard_id}/widgets`. It holds the position and
   the section of the old widget.
3. If `args.replace` is true, send
   `DELETE /api/dashboards/{dashboard_id}/widgets/{widget_id}`. If step 1
   or 2 fails, do not remove the old widget.
4. Set `last_widget_ids` to the id of the new widget.

The new widget keeps `size`, `default_view` and `viewport` of the old
config. It does not keep `chartIds` and `titles` (they name the old
charts) or `title` (it can name the old period). The old insight stays.
The planner reads the data of a chart from the first statistics row of its
insight. A chart with no statistics row (a chart that the agent made with
code), imagery, an alerts list and a note get no step and a note.

`replace` is false when `CHANGE_PERIOD_REPLACES` in
`src/api/services/zap/edits.py` is false (open decision 2): then skip
step 3, and the new widget stands next to the old widget.

**`remove`** (phase 5, always tier 2): a widget, or a section with or
without its widgets.

```json
{
  "kind": "remove",
  "title": "Remove section: \"Fires\"",
  "detail": "its 1 widget moves to the top level",
  "args": {
    "dashboard_id": "5b0c4f9e-...",
    "target_type": "section",
    "widget_id": null,
    "section_id": "77c0...",
    "label": "Section \"Fires\" (1 widget)",
    "delete_widgets": false,
    "widget_labels": ["Chart \"Tree cover loss due to fires\" in section \"Fires\""]
  }
}
```

- For `target_type` `"widget"`, send
  `DELETE /api/dashboards/{dashboard_id}/widgets/{widget_id}`. The insight
  of the widget stays, so "add the chart again" can bring it back.
- For `"section"`, send
  `DELETE /api/dashboards/{dashboard_id}/sections/{section_id}?delete_widgets={delete_widgets}`.
  With `false`, the widgets of the section go to the top level. Show
  `widget_labels` in the preview.

#### No steps

The plan has no steps and one note when:

- The dashboard does not exist, or the user is not its owner.
- The dashboard has no area.
- jev selects `edit` (delete or publish the dashboard, write a note) or
  `none`.
- The request is about more than one area, or the parts of an area (for an
  addition only).
- `add_section` or `rename` with no new name in the words of the user
  (Clairic `title`). Zap writes no text.
- `move`, `resize`, `rename`, `change_period` or `remove` when jev selects
  "none of these" for the target. Zap does not guess a target.
- `move` to a place that is not on the dashboard, or to the place where the
  widget is now. `move` on a dashboard with no section and no widget in a
  section.
- `resize` to the width that the widget has now. `rename` to the name that
  the item has now.
- `change_period` with no time in the request, for a widget that zap
  cannot build again, or to the dates that the widget shows now.
- `add_chart` or `add_map` with no dataset in the request and none in
  `current`.
- `add_template` with no template that fits.
- `add_imagery` for a time before Sentinel-2 (June 2015).

#### The `action` question

jev gets the `action` question in its first call on a dashboard page. The
options are `add_chart`, `add_map`, `add_template`, `add_imagery`,
`add_section`, `move`, `resize`, `rename`, `change_period`, `remove`,
`edit` and `none`. The `edit` option is not in section 5. It catches the
actions that stay outside zap (tier 3), so that jev does not select an
addition or an edit for them. `edit` and `none` give no steps.

#### The `target` question

For `move`, `resize`, `rename`, `change_period` and `remove`, a second jev
call asks the `target` question. Its options are the items of the
dashboard, each with a readable label, and "none of these":

| Action | Options |
|---|---|
| `move`, `resize` | The widgets |
| `change_period` | The charts and the dataset maps that zap can build again |
| `rename` | The dashboard name and the sections |
| `remove` | The widgets and the sections |

A widget label is its kind, its title and its place:
`Chart "Tree cover loss per year" in section "Overview"`. A section label
has the number of its widgets: `Section "Fires" (2 widgets)`. The items of
`last_widget_ids` and `last_section_ids` come first, with the mark
"The last edit: ". The jev state also has a "Last edit" line.

The same call asks the other choices of the action: `destination` for
`move` (each section and "the top level"), `size` for `resize` (half width
or full width), and `widgets` for `remove` when the dashboard has sections
("keep its widgets", the default, or "remove its widgets with the
section"). The `widgets` decision is in the plan only when the target is a
section.

## Eval

Zap needs a labelled set before the Clairic change, so that the change can
be measured.

- **Map set.** The single-area gold prompts give the dataset, the area and
  the dates (the dates are in the `pull_data` arguments). Add requests that
  the option lists cannot hold: date ranges, months, long place names,
  canopy values. Add follow-up pairs.
- **Dashboard set.** Requests against two or three fixed dashboards, with
  the expected action, target and tier. Include requests that must get a
  confirmation and requests that must change nothing.
- As in stac-zap: write the field instructions on a dev part only, and run
  the test part one time.
- Report the wrong edits that were applied with no confirmation as a
  separate number. This number sets the thresholds.

## Baseline

Run on 2026-11-12 with jev `typesafe/jev-1.13`, the planner of `main` at
`1784eab6`, and the map set in `tests/evals/zap/` (51 dev cases, 53 test
cases). `scripts/zap_eval.py` runs the set. `tests/evals/zap/README.md`
gives the scoring rules. The raw results are in
`tests/evals/zap/results/2026-11-12-dev.json` and `2026-11-12-test.json`.

Correct values for each field:

| Field | Dev | Test | Total |
|---|---|---|---|
| Dataset | 51/51 | 53/53 | 104/104 (100%) |
| Area | 45/51 | 49/53 | 94/104 (90%) |
| Time | 32/50 | 36/51 | 68/101 (67%) |
| Context layer | 32/35 | 39/41 | 71/76 (93%) |
| Canopy cover | 29/29 | 31/33 | 60/62 (97%) |
| No change | 4/5 | 4/4 | 8/9 |
| All fields of a case | 25/51 | 32/53 | 57/104 (55%) |
| Median time of a plan | 562 ms | 558 ms | |

Cases with all tested fields correct, for each kind of case:

| Kind | Dev | Test | Total |
|---|---|---|---|
| Gold prompts | 9/21 | 16/23 | 25/44 |
| Gold prompts, other languages | 1/3 | 2/2 | 3/5 |
| Free date range | 0/2 | 0/3 | 0/5 |
| Month or day (alerts) | 0/3 | 0/3 | 0/6 |
| Period back from today | 1/3 | 2/3 | 3/6 |
| Place name of more than four words | 3/3 | 3/3 | 6/6 |
| Canopy cover value | 3/3 | 3/4 | 6/7 |
| Follow-up pairs | 4/8 | 4/8 | 8/16 |
| No change | 4/5 | 4/4 | 8/9 |

What the baseline shows:

- **Time is the weakest field.** jev changes each free range to the nearest
  option: "from 2015 to 2020" becomes "since 2015", "2010-2015" becomes
  the full record. Each month or day of the alerts becomes its year.
  "The last 3 months" and "the last 6 months" become the last 12 months.
  A range that ends before today, such as "between 2001 and 2024", also
  ends on the last date of the dataset.
- **The area fails in the `place` question, not in the area question.**
  In all 10 failures, the span that jev selected has extra words
  ("Corona Forestal protected area", "in Cogo Eq Guinea", "Las Palmas
  Canarias ESP"), a possessive ("Indonesia's"), a name that is not English
  ("España"), or no word breaks (Chinese). Then `search_aois` finds no
  area, or jev rejects all the areas that it finds.
- **Long place names did not fail.** `search_aois` found the area from a
  span of four words for all six cases. The limit of four words is real,
  but this set does not show it.
- **Follow-up requests lose the settings.** "since 2015" after "primary
  forest loss in Pará" drops the forest type. "fires instead" drops the
  forest type and the dates. "now show 2020" drops the canopy cover. "use
  a 75% canopy threshold" drops the forest type.
- **The dataset is always correct**, also in follow-up requests and in
  other languages.

Phase 2 must improve time and area on this set, with no loss on dataset,
context layer and canopy cover.

## Phase 2 result

Run on 2026-11-12 with jev `typesafe/jev-1.13`, Clairic
`cloudflare/clairic` (`cloudflare/clairic-20261029`) and the same map set
as the baseline. The field instructions and the calendar rules were tuned
on the dev part only. The test part ran one time, after the tuning. The raw
results are in `tests/evals/zap/results/2026-11-12-dev-phase2.json` and
`2026-11-12-test-phase2.json`.

A follow-up case now sends the `state` of the plan of its first prompt (see
`tests/evals/zap/README.md`). Thus, a wrong first plan also counts against
its follow-up. The baseline sent only the dataset and the area of the fixed
`current`.

Correct values for each field:

| Field | Dev | Test | Total | Baseline total |
|---|---|---|---|---|
| Dataset | 51/51 | 53/53 | 104/104 (100%) | 104/104 (100%) |
| Area | 48/51 | 51/53 | 99/104 (95%) | 94/104 (90%) |
| Time | 50/50 | 47/51 | 97/101 (96%) | 68/101 (67%) |
| Context layer | 34/35 | 40/41 | 74/76 (97%) | 71/76 (93%) |
| Canopy cover | 29/29 | 33/33 | 62/62 (100%) | 60/62 (97%) |
| No change | 5/5 | 4/4 | 9/9 | 8/9 |
| All fields of a case | 47/51 | 46/53 | 93/104 (89%) | 57/104 (55%) |
| Median time of a plan | 695 ms | 659 ms | | 562 ms, 558 ms |

Cases with all tested fields correct, for each kind of case:

| Kind | Dev | Test | Total | Baseline total |
|---|---|---|---|---|
| Gold prompts | 19/21 | 19/23 | 38/44 | 25/44 |
| Gold prompts, other languages | 1/3 | 2/2 | 3/5 | 3/5 |
| Free date range | 2/2 | 3/3 | 5/5 | 0/5 |
| Month or day (alerts) | 3/3 | 1/3 | 4/6 | 0/6 |
| Period back from today | 3/3 | 3/3 | 6/6 | 3/6 |
| Place name of more than four words | 3/3 | 3/3 | 6/6 | 6/6 |
| Canopy cover value | 3/3 | 4/4 | 7/7 | 6/7 |
| Follow-up pairs | 8/8 | 8/8 | 16/16 | 8/16 |
| No change | 5/5 | 4/4 | 9/9 | 8/9 |

The "done when" of phase 2 holds: time and area are better than the
baseline, and dataset, context layer and canopy cover are not worse.

What changed in the planner:

- Clairic call A (the request only) gives the place and the canopy cover.
  Clairic call B (the app context, today's date and the request) gives the
  time. Both calls and the first jev call start at the same time.
- Code makes the range for these time words: whole years ("in 2025",
  "2015-2020", "since 2015", "until 2010"), months in English ("March
  2026", "from January to April 2025", "since May"), seasons, quarters,
  half years, periods back from today, "recent" (the last 12 months, as the
  jev option) and "all years". On the dev part, Clairic gave a wrong last
  day for most years and some months, for example 2026-12-12 for "in 2025"
  and 2026-03-02 for "March 2026". "Today" or "now" alone names no time.
  In the two runs, code made 56 of the 104 ranges.
- When `search_aois` finds nothing for the place words, the planner tries
  again with a cleaned name: no type word at the end ("Corona Forestal
  protected area"), no possessive, no text in brackets, and a comma in place
  of "in" ("Pocho in Cordoba").
- The canopy cover snaps to the nearest value of the dataset. A value more
  than 5 points from a permitted value adds a note.
- The planner starts from the full `current` and changes only what the
  request names. jev gets a `keep` option for the forest type when the map
  shows one. When the current dates are all the dates of the current
  dataset, they do not count as a selected period.
- Each decision has a `source`: `jev`, `clairic` or `code`. `ZapPlan.state`
  is the state after the steps.
- A Clairic call that gets a 429 or a 5xx error tries again one time after
  0.3 s. The dev runs got "Capacity temporarily exceeded" (429) when many
  calls ran at the same time.

The fallback: the first jev call also asks the `place` and `period`
questions of phase 1, so a Clairic failure adds no time. When call A fails,
the planner uses the jev place and asks the jev `canopy` question. When
call B fails, or its answers make no range, the planner uses the jev period.
The unit tests cover each case. A dev run with a wrong extractions URL
(all Clairic calls fail) gave dataset 51/51, area 47/51, time 31/50, context
layer 32/35, canopy cover 29/29, no change 4/5 and all fields 26/51, with
each value from jev. This is near the dev baseline (45, 32, 32, 29, 4 and
25).

The cost: the median time of a plan increased by about 120 ms. The first
jev call still asks the `place` and `period` questions, so the jev cost
did not decrease, and the two Clairic calls add about $0.00004 each.

The cases that still fail:

| Case | Field | Cause |
|---|---|---|
| d-14, d-16 | Area | The name is not English ("España", "中国"). Clairic gives the words of the request and does not translate them. `search_aois` finds English names only |
| d-10 | Area | jev selects the municipality of Huelva, not the province (probability 0.5) |
| t-05 | Area | The place words "Blackfeet Indian reservation in Montana USA" find no area, also in the cleaned form. The baseline found it from a shorter span. A new failure |
| t-06 | Area | "Champoton community land in Mexico" finds no area. The baseline also failed |
| d-23, t-12 | Context layer | jev selects no forest type for "deforestation". The baseline also failed |
| t-15 | Time | The request compares two months. Clairic gives the first month only. The expected range has both months |
| t-20 | Time | The request compares two periods. Clairic gives the first period, 2000-2010. The expected range is the whole record. A new failure |
| t-30 | Time | "last month": Clairic gives 2026-10-01 to 2026-10-12, not the full month. The rule for a period back from today leaves "last month" to Clairic |
| t-31 | Time | "between December 2024 and February 2025": the month rule takes only one year, and Clairic ends on 2025-02-02 |

Possible next steps, from these failures: a month rule for "last month"
and for a range of months over two years, a cleaned form that removes
words such as "Indian reservation" and "community land", and English
names before `search_aois`. Add dev cases for each before a change, because
t-30 and t-31 are in the test part.

## Phase 4 result

The backend part of phase 4 ran on 2026-11-12 with jev `typesafe/jev-1.13`
and Clairic `cloudflare/clairic`. The dashboard set is in
`tests/evals/zap/` (`dashboards.yaml`, `dashboard-dev.yaml` with 32 cases,
`dashboard-test.yaml` with 32 cases). `tests/evals/zap/README.md` gives the
scoring rules. The texts of the `action` options and the thresholds were
tuned on the dev part only. The test part ran one time, after the tuning.
The raw results are in `tests/evals/zap/results/`:
`2026-11-12-dashboard-dev-phase4-v3.json` (the last dev run) and
`2026-11-12-dashboard-test-phase4.json`.

Correct values for each field:

| Field | Dev | Test | Total |
|---|---|---|---|
| Action (also "no steps") | 30/32 | 32/32 | 62/64 (97%) |
| Dataset | 13/13 | 14/15 | 27/28 |
| Time | 16/16 | 16/18 | 32/34 |
| Forest type | 8/8 | 11/11 | 19/19 |
| Canopy cover | 9/9 | 10/10 | 19/19 |
| Template | 2/2 | 4/4 | 6/6 |
| Cloud cover | 3/3 | 3/3 | 6/6 |
| Confirmation as expected | 18/19 | 19/22 | 37/41 |
| All fields of a case | 30/32 | 27/32 | 57/64 (89%) |
| Median time of a plan | 512 ms | 414 ms | |

The additions:

| | Dev | Test | Total |
|---|---|---|---|
| Plans with an addition | 19 | 22 | 41 |
| Wrong additions | 1 | 3 | 4 |
| **Wrong additions applied with no confirmation** | **0** | **2** | **2** |
| Correct additions held for a confirmation that is not necessary | 0 | 1 | 1 |
| Requests that must add nothing, with no steps | 12/12 | 10/10 | 22/22 |

All 22 requests that must add nothing got no steps: the actions of a later
phase (remove, move, rename, resize, change a period, delete, publish, a
note), the greetings and questions, and the requests for more than one
area.

The cases that fail:

| Case | Field | Cause | Confirmation |
|---|---|---|---|
| dd-14 | Action | "add the analysis of natural forest loss since 2021": jev selects `add_chart` (0.55), not `add_template` (0.45). The chart is tree cover loss in natural forest since 2021, which is near to the request | Yes |
| dd-30 | Action | "tree cover loss" alone: jev selects `none` (0.77). No steps, so nothing wrong is added | |
| dt-10 | Time | "the last month": Clairic gives 2026-10-01 to 2026-10-12. The same failure as t-30 of the map set | **No** |
| dt-18 | Time | "December 2024 to February 2025": the month rule takes one year only. The same failure as t-31 of the map set. The imagery is around 2025-01-01, ±32 days, which is near to the request | **No** |
| dt-32 | Dataset | "and a chart of it at 10% canopy" after tree cover loss: jev selects tree cover (2000), probability 0.63 | Yes |
| dt-03 | Confirmation | "a chart of the integrated alerts in October 2026": correct, but the action probability is 0.62 | Yes, not necessary |
| dt-29 | Confirmation | "deforestation": correct (a tree cover loss chart), but with no confirmation. The case expects one, because the request does not say chart or map | No |

The two wrong additions with no confirmation are time errors of Clairic
and of the month rule. The tiers do not catch them, because Clairic is sure
of its wrong value. The fixes of the map set for "last month" and for a
range of months over two years (see "Phase 2 result") also fix these
cases.

What the dev part changed:

1. Run 1 (the first texts, minimum probability 0.6): one wrong addition
   with no confirmation (dd-14, action 0.71 and 0.28). The action labels
   were longer than 80 characters, so the panel cut them.
2. Run 2: shorter action texts (at most 77 characters), and the
   `add_template` text names the three sections. dd-14 dropped to 0.60
   and needed a confirmation. "something about fires" (dd-31) was at 0.62
   and needed no confirmation.
3. Run 3: minimum probability 0.7. dd-31 needs a confirmation. All
   correct additions of the dev part stayed at tier 1.

The map set after the change (raw results
`tests/evals/zap/results/2026-11-12-dev-phase4.json` and
`2026-11-12-test-phase4.json`):

| Field | Phase 4 total | Phase 2 total |
|---|---|---|
| Dataset | 104/104 | 104/104 |
| Area | 99/104 | 99/104 |
| Time | 97/101 | 97/101 |
| Context layer | 74/76 | 74/76 |
| Canopy cover | 62/62 | 62/62 |
| No change | 9/9 | 9/9 |
| All fields of a case | 93/104 | 93/104 |
| Median time of a plan | 810 ms, 808 ms | 695 ms, 659 ms |

The same cases fail as in phase 2. The map path makes no new call: it only
adds `options`, `clear`, `tier` and `needs_confirmation` to the plan. The
median time is higher than in phase 2. The cause is not known. The
dashboard runs of the same hour, which make the same kind of calls, had a
median of 414 ms to 512 ms.

`add_imagery` is in phase 4. An imagery widget needs a mosaic that exists.
The mosaic id is a token of the recipe (the area, the date, the window, the
cloud cover and the number of scenes), so the planner can compute the id
and the tile URLs with no server change. The frontend builds the mosaic
with `POST /mosaic/create/{source}/{src_id}` before it adds the widget. A
unit test checks that the token of the planner is the same as the token of
the endpoint. The eval did not build a mosaic, and no live run sent a step
to the dashboard endpoints.

Not tested: the planner with a dashboard from the database
(`load_dashboard`) is tested with a fake row only. No run used a real
dashboard.

## Phase 5 result

The backend part of phase 5 ran on 2026-11-12 with jev `typesafe/jev-1.13`
and Clairic `cloudflare/clairic`. It adds the actions `add_section`,
`move`, `resize`, `rename`, `change_period` and `remove`, the `target`
question, the Clairic `title` field, the last-edit ids, `choose`, and the
two month rules. The code is in `src/api/services/zap/edits.py` (the edit
plans) and `board.py` (the dashboard items and their labels). The step
contract is in "8. Dashboard step contract".

The eval:

- The fixed dashboards got ids, a second section on `para`, widgets with
  near titles ("Tree cover loss per year", "Primary forest loss per
  year"), and the analysis of each chart and dataset map.
- The phase 4 cases of the kind "later phase" now expect the edit (for
  example a `remove` with its target), or no steps for delete, publish and
  a note.
- New cases: 28 in the dev part (`dd-33` to `dd-60`) and 27 in the test
  part (`dt-33` to `dt-59`). They have each new action, targets that are
  not on the dashboard, near titles, "remove that" after an addition (with
  the last-edit ids), the removal of a section with and without its
  widgets, and requests that must change nothing. Four of the dev cases
  (`d-52`, `d-53`, `dd-33`, `dd-34`) are for the month rules.
- The action texts were tuned on the dev part only (three runs). The test
  parts ran one time, after the tuning. The raw results are in
  `tests/evals/zap/results/`: `2026-11-12-dashboard-dev-phase5-v3.json`,
  `2026-11-12-dashboard-test-phase5.json`, `2026-11-12-dev-phase5.json`
  and `2026-11-12-test-phase5.json`.

### The dashboard set

Correct values for each field (dev 60 cases, test 59 cases):

| Field | Dev | Test | Total |
|---|---|---|---|
| Action (also "no steps") | 56/60 | 59/59 | 115/119 (97%) |
| Target | 21/21 | 21/22 | 42/43 |
| Destination (`move`) | 3/3 | 3/3 | 6/6 |
| Width (`resize`) | 5/5 | 4/4 | 9/9 |
| Title (`rename`, `add_section`) | 5/5 | 5/5 | 10/10 |
| Its widgets (`remove` of a section) | 3/3 | 2/3 | 5/6 |
| Dataset | 13/13 | 14/15 | 27/28 |
| Time | 19/19 | 22/22 | 41/41 |
| Forest type | 8/8 | 11/11 | 19/19 |
| Canopy cover | 8/8 | 10/10 | 18/18 |
| Template | 2/2 | 4/4 | 6/6 |
| Cloud cover | 3/3 | 3/3 | 6/6 |
| Tier and confirmation as expected | 37/43 | 42/46 | 79/89 |
| All fields of a case | 52/60 | 53/59 | 105/119 (88%) |
| Median time of a plan | 589 ms | 598 ms | |

Against phase 4, on the 64 cases of phase 4 (the expectations of the 15
"later phase" cases changed, see above):

| | Phase 5 | Phase 4 |
|---|---|---|
| Action | 61/64 | 62/64 |
| All fields of a case | 53/64 | 57/64 |
| Time | 35/35 | 32/34 |
| Wrong additions applied with no confirmation | 0 | 2 |
| Correct additions held for a confirmation that is not necessary | 7 | 1 |

The plans with steps, in the two parts together:

| | Plans | Wrong | **Wrong, applied with no confirmation** | Correct, held for a confirmation that is not necessary |
|---|---|---|---|---|
| Additions | 40 | 1 (dt-32) | **0** | 7 |
| Edits (`add_section`, `move`, `resize`, `rename`, `change_period`) | 34 | 3 (dd-02, dd-12, dt-45) | **0** | 0 |
| Removals | 15 | 1 (dt-56) | **0** | 0 |

- Requests that must change nothing, with no steps: 28/28 (15 dev, 13
  test). This includes targets, places and names that are not on the
  dashboard, "remove everything", delete, publish and a note.
- "remove that" after an addition removes the added widget (dd-55, dt-54),
  and "make it half width" and "move it to the Drivers section" select the
  added widget (dd-56, dt-55). The "done when" of phase 5 holds for the
  backend: no wrong removal is applied with no confirmation.

The cases that fail:

| Case | Field | Cause | Confirmation |
|---|---|---|---|
| dd-02 | Action | "chart primary forest loss between 2002 and 2010": jev selects `change_period` (0.85) of the "Primary forest loss per year" chart. The new board has this chart, so the request can mean it | Yes (`change_period`) |
| dd-12 | Action | "add the near real-time monitoring section": jev selects `add_section` (0.53), not `add_template` (0.47). The title is "near real-time monitoring section" | Yes |
| dd-34 | Action | "add Sentinel-2 imagery from November 2023 to March 2024": jev selects `change_period` (0.88). No target fits, so the plan has no steps | No steps |
| dd-30 | Action | "tree cover loss" alone: `none`, as in phase 4 | No steps |
| dt-32 | Dataset | "and a chart of it at 10% canopy": tree cover (2000), as in phase 4 | Yes |
| dt-45 | Target | "show the fire chart for 2024 only": the flux chart (0.53), the fire chart second (0.28). The preview shows the fire chart as the first chip | Yes |
| dt-56 | Its widgets | "undo that, remove the new section": "with its widgets" (0.65). The section is empty, so nothing more is removed | Yes |

The cost: on the additions of phase 4, the action decision is less sure.
With twelve action options, the probability of the selected addition
dropped below 0.7 for seven correct additions (dd-10, dd-13, dd-14, dd-32,
dt-02, dt-03, dt-16), so these need a confirmation. None of them is wrong.
The minimum probability (0.7) did not change. A lower minimum would apply
these additions with no confirmation, but the dev part has too few
cases near the limit to set a new value.

What the dev part changed:

1. Run 1 (the first texts): `change_period` took additions with a date
   (dd-02, dd-33 at 0.41, dd-34), and `add_section` took template requests
   (dd-12).
2. Run 2: shorter addition texts and the rule "an edit option only when the
   request names something on the dashboard". The `add_template` text lost
   "natural", and dd-14 became a wrong chart with no confirmation. Not
   kept.
3. Run 3 (kept): the addition texts of phase 4, an `add_section` text that
   says "empty, with no content", a `change_period` text that says "with no
   new widget", and the rule "pick `change_period` only when the request
   asks to change a widget that is there". dd-33 became correct.

### The month rules

"Last month" and "the previous month" are now the full calendar month
before today. A range of months with two years ("December 2024 to
February 2025") gives each month its own year. Before the fix, d-52, d-53
and dd-33 failed on the time and dd-34 passed; after it, all four pass. In
the test parts, t-30, t-31, dt-10 and dt-18 now pass.

### The map set

| Field | Phase 5 total | Phase 4 total |
|---|---|---|
| Dataset | 106/106 | 104/104 |
| Area | 101/106 | 99/104 |
| Time | 101/103 | 97/101 |
| Context layer | 76/78 | 74/76 |
| Canopy cover | 62/62 | 62/62 |
| No change | 9/9 | 9/9 |
| All fields of a case | 97/106 | 93/104 |
| Median time of a plan | 724 ms, 797 ms | 810 ms, 808 ms |

The dev part has two new cases (d-52, d-53), both correct. On the 104
cases of phase 4, time is 99/101 and all fields 95/104. t-30 and t-31 are
correct. The other failures are the same as in phase 2: d-10, d-14, d-16,
t-05, t-06 (area), d-23, t-12 (context layer), t-15 and t-20 (time).

### Not tested

- No live run sent an edit step to the dashboard endpoints. The step args
  follow the request models of `src/api/schemas.py` and the routers.
- `load_dashboard` with its statistics lookup (`_insight_analyses`) ran
  with fake rows only. No run used a real dashboard.
- `choose` is tested with unit tests only. The eval runs no chip
  selection.

## Phases

Each phase is one or more PRs and can ship alone behind `ff=zap`.

| Phase | Content | Done when |
|---|---|---|
| 1 (done, 2026-11-12) | Map eval set and script. Baseline of zap today | The baseline numbers are in this document (see "Baseline") |
| 2 (done, 2026-11-12) | `extract.py` with the jev fallback. Full `ZapCurrent`. `state` in the plan | The map set is better than the baseline on time and area, and not worse on dataset, context layer and canopy cover |
| 3 | History trail in the browser, with its row limit, and undo on the map (frontend). Top options in the decisions (the backend sends them since phase 4) | A follow-up request keeps the earlier settings; undo and row selection restore the map |
| 4 (backend done, 2026-11-12) | Zap on dashboards, tier 1 additions: `action` question, the dashboard steps in the frontend, the dashboard trail. Backend: the dashboard planner, the step contract ("8. Dashboard step contract"), `tier`, `needs_confirmation` and the top options of the decisions, the dashboard eval set | A request adds a chart, a map, a template or imagery to a dashboard, and the trail shows the edit |
| 5 (backend done, 2026-11-12) | Tier 1 layout edits and tier 2 edits: `target` question, preview and confirmation, thresholds from the dashboard set. Backend: the edit steps and their contract, the `target` question, the Clairic `title`, the last-edit ids, `choose`, the month rules, the dashboard set for the edits ("Phase 5 result") | No wrong removal is applied with no confirmation in the dashboard set; "remove that" after an addition removes the added widget |
| 6 | `view` question, after the view registry merges | `add_chart` can select each view of a dataset |

## Risks

- **Alpha APIs.** The decisions API and the extractions API are alpha, and
  Clairic is a preview. The fallback covers Clairic. Nothing covers jev.
- **Declines.** jev declines poorly (PR #841). On a dashboard, a wrong
  `action` is worse than on the map, because it writes data. Tier 2 and the
  thresholds are the protection, and the dashboard set must have decline
  cases.
- **No undo on dashboards.** A wrong tier 1 edit stays until the user
  corrects it. Additions and layout changes are easy to correct. A wrong
  `change_period` loses the old period of the widget, which is why it is
  in tier 2.
- **Steps that fail in the middle.** The frontend runs the steps one by
  one, so a failure can leave a part of the plan applied.
- **English only.** The calendar rules in code read English words. Other
  languages use the `start` and `end` dates of Clairic with no rule.
- **Analysis time.** `add_chart` waits for an `/api/analyze` job. The
  frontend adds the widget when the job ends, as `ZapRunner` does for the
  chart step today. If the user leaves the page before that, the insight
  exists but the widget does not.

## Decisions

Agreed on 2026-11-12:

- **History storage.** The browser only, with a row limit. The backend
  stores no history.
- **Undo on dashboards.** None in this plan. The user makes a new request
  to take back an edit. A real undo can come later.

Open, for agreement before phase 2:

1. **Where dashboard steps run.** Proposed: in the frontend, through the
   dashboard endpoints that exist. With no undo, a server apply endpoint
   has no clear benefit. It can come with a real undo.
2. **`change_period`.** Proposed: replace the widget after a confirmation.
   The alternative keeps the old widget and adds the new one next to it,
   which loses nothing but leaves the user to remove the old one. Phase 5
   replaces it. `CHANGE_PERIOD_REPLACES` in `src/api/services/zap/edits.py`
   selects the alternative (the step then has `replace: false`).
3. **Text.** Proposed: zap writes no text. A name or a note is the words of
   the user from the `title` field. Text widgets with new text stay with
   the assistant.
4. **Access.** Proposed: admins only and `ff=zap` until phase 5 passes its
   eval.
5. **Phase order.** Proposed: extraction first, because the dashboard
   actions need correct dates. If dashboards are more urgent, phase 4 can
   go before phase 3.
