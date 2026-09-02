---
name: dashboard
description: Create a dashboard for an area, group its content into sections, and fill it with insights (new or recalled), map widgets, and text notes.
when_to_use: User asks to build/create a dashboard for a place, to add an insight/analysis to a dashboard, to add a map layer / satellite imagery to a dashboard, to monitor an area for recent disturbance, or to group, organize or restructure a dashboard's content. Not for one-off analysis without a dashboard — use `analyze`.
requires: create_dashboard, add_to_dashboard, add_map_widget, add_text_widget, edit_text_widget, add_dashboard_section, add_nrt_monitoring_section, edit_dashboard_section, move_dashboard_widget, inspect_view_context, send_nudge, search_insights
---

# Dashboards

A dashboard is a persistent collection of widgets for ONE area (a country, a
state, a protected area). Widgets are insights, map layers, or free-form text notes. Widgets
reference or snapshot work that already exists — adding to a dashboard never
recomputes anything.

A dashboard has one optional level of grouping: **sections**. A section has a
title and an optional description that says what it is for. Every widget
either belongs to one section or stays ungrouped; ungrouped widgets render
above the first section. Order matters and is kept: sections render in their
own order, widgets in order within their section.

# Read-only sections

Some sections are built by a recipe in one piece rather than widget by
widget — `inspect_view_context` marks them `read-only`. They are a record of
one build, so **nothing about them can be changed**: not the title, not the
description, not the widgets, not their order. The tools refuse it.

If the user asks to change one, say it cannot be edited and offer to delete
it and build a new one. Deleting it removes its widgets with it. Never put a
new widget in one, and never move a widget out of one — put it in another
section or leave it ungrouped.

# Monitoring an area ("watch this place", "recent alerts for X")

`add_nrt_monitoring_section(dashboard_id?, days?)` builds a whole
near-real-time monitoring section: a chart of integrated disturbance alerts,
a map of those alerts, and satellite imagery of the same area and period.

- It pulls its own data. Do **not** run `pick_dataset`, `pull_data`,
  `generate_insights` or `show_imagery` first — that would duplicate the
  work and the widgets.
- It needs a dashboard with an area; `create_dashboard` first if there is
  none.
- `days` is the alert window counted back from today (default 90).
- It takes a while. Say what you are doing before you call it.
- Satellite imagery is skipped for areas too large for a mosaic, or periods
  with no clear scenes; the reply says so and the section is still built.
  Pass that on rather than retrying.
- The section it writes is read-only (see above).

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
2. When the request covers **two or more distinct topics**, create one
   section per topic first with `add_dashboard_section(title, description?)`,
   then add each topic's widgets with `section="<that title>"`. For a
   single-topic request, skip sections — do not create a section that would
   hold everything.
3. Per topic, reuse existing work before computing: if the user refers to an
   earlier finding, `search_insights` → `add_to_dashboard`. Otherwise run the
   `analyze` pipeline (pick_dataset → pull_data → generate_insights) →
   `add_to_dashboard`. If the user asks for a map/layer/imagery view of a
   topic, add it with `add_map_widget` after the dataset is picked (or after
   `show_imagery`) — a map widget does not need an insight.
4. Give a short progress message per topic added.

# Sections

- `add_dashboard_section(title, description?)` creates an empty section.
  Titles are short and topical ("Deforestation", "Land cover", "Fires"), not
  sentences. Use the description for the intent — one or two lines on what
  the section is meant to answer — when it is not obvious from the title.
- `add_to_dashboard`, `add_map_widget` and `add_text_widget` all take
  `section` (a section title or id) to place the widget. Leave it out for an
  ungrouped widget.
- `edit_dashboard_section(section?, title?, description?)` renames a section
  or restates its intent. It defaults to the dashboard's only section; when
  several exist, pass the title.
- `move_dashboard_widget(widget_id, section?|ungroup?, position?)` regroups a
  widget that is already on the dashboard — into a section, or back out to
  the top level. Get widget ids from `inspect_view_context` first; it lists
  every widget with its id.
- Check what is already there before grouping: `inspect_view_context` lists
  the dashboard's sections and which widgets sit in each. Reuse a matching
  section rather than creating a near-duplicate — a widget belongs in the
  section whose topic it answers.
- Never reorganize a dashboard the user did not ask you to reorganize.

# Adding a single insight ("add this to my dashboard")

`add_to_dashboard` — it defaults to the current insight in state and the
dashboard in state/on screen. Recall the insight first (`search_insights`)
only if the user refers to a past finding that is not the current one. If the
dashboard already has sections, pass the `section` whose topic the insight
answers; add it ungrouped only when none fits.

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
