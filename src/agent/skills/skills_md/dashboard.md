---
name: dashboard
description: Create a dashboard for an area and fill it with insights (new or recalled), map widgets, and text notes.
when_to_use: User asks to build/create a dashboard for a place, to add an insight/analysis to a dashboard, or to add a map layer / satellite imagery to a dashboard. Not for one-off analysis without a dashboard — use `analyze`.
requires: create_dashboard, add_to_dashboard, add_map_widget, add_text_widget, edit_text_widget, send_nudge
---

# Dashboards

A dashboard is a persistent collection of widgets for ONE area (a country, a
state, a protected area). Widgets are insights, map layers, or free-form text notes. Widgets
reference or snapshot work that already exists — adding to a dashboard never
recomputes anything.

# Which dashboard to use

- If the user is viewing a dashboard (view_context has a `dashboard_id`, page
  `dashboard` — check with `inspect_view_context` if unsure) or one was
  created/used earlier this conversation, **reuse it**: `add_to_dashboard`
  defaults to it.
- Only call `create_dashboard` when there is no dashboard yet, or the user
  explicitly asks for a new one. It needs an AOI in state — run `pick_aoi`
  first if none is selected. One area per dashboard; for "a dashboard for X
  and Y", ask the user to pick one area (multi-area portfolios are not
  supported yet).
- If it's genuinely unclear which the user means — e.g. they say "make a
  dashboard" while one is already active this thread, or "add this" when it
  could plausibly read as "start a new one" — don't guess: call
  `send_nudge(nudge_type="dashboard_choice", options=["Create a new
  dashboard", "Update the current dashboard"])` and wait for their answer
  before calling `create_dashboard` or `add_to_dashboard`.

# Composing ("build me a dashboard for X about A, B, C")

1. `pick_aoi` for X (skip if already selected), then `create_dashboard`.
2. Per topic, reuse existing work before computing: if the user refers to an
   earlier finding, `search_insights` → `add_to_dashboard`. Otherwise run the
   `analyze` pipeline (pick_dataset → pull_data → generate_insights) →
   `add_to_dashboard`. If the user asks for a map/layer/imagery view of a
   topic, add it with `add_map_widget` after the dataset is picked (or after
   `show_imagery`) — a map widget does not need an insight.
3. Give a short progress message per topic added.

# Adding a single insight ("add this to my dashboard")

`add_to_dashboard` — it defaults to the current insight in state and the
dashboard in state/on screen. Recall the insight first (`search_insights`)
only if the user refers to a past finding that is not the current one.

# Adding a map layer ("add this layer / the imagery to my dashboard")

`add_map_widget(layer="dataset")` snapshots the currently selected dataset
layer — run `pick_dataset` first if none is selected.
`add_map_widget(layer="imagery")` snapshots the Sentinel-2 mosaic — run
`show_imagery` first. Build the layer/imagery for the dashboard's area. Map
widgets render focused on the dashboard's area automatically.

# Adding a text note ("add a note / summary / explanation to my dashboard")

`add_text_widget(text)` puts a markdown note on the dashboard — use it when
the user wants to add a summary, section intro, caveat or explanation. The
text is markdown; compose it yourself (concise, no raw data). To rewrite a
note, use `edit_text_widget(text)` — it defaults to the dashboard's only text
widget; if several exist the tool lists their ids so you can retry with
`widget_id`.

# Stop conditions

- Add only what the user asked for — never keep adding widgets unprompted.
- After the requested widgets are added, confirm what the dashboard now
  contains and stop. Suggest at most one follow-up topic; do not run it.
- If a step fails (no data, insight not found), report it and continue with
  the remaining topics rather than aborting the whole dashboard.
