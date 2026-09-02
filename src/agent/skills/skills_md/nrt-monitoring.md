---
name: nrt-monitoring
description: Build a near-real-time monitoring section on a dashboard — an alerts chart, an alerts map and satellite imagery for one area and period, in one step.
when_to_use: User asks to monitor or watch an area, or asks for recent/near-real-time disturbance on a dashboard. Not for a one-off look at alerts without a dashboard — use `analyze`, or `show-imagery` for imagery alone.
requires: add_nrt_monitoring_section, create_dashboard, pick_aoi, inspect_view_context
---

# Near-real-time monitoring sections

`add_nrt_monitoring_section(dashboard_id?, days?)` builds a whole section on
a dashboard in one call: a chart of integrated disturbance alerts over the
period, a map of those alerts, and satellite imagery of the same area and
period.

It is not like the other dashboard tools. They snapshot work the
conversation already did; this one does the work itself.

# Steps

1. The dashboard: reuse the one the user is viewing or made earlier this
   conversation. If there is none, `pick_aoi` then `create_dashboard` — the
   section covers the dashboard's own area, so the dashboard has to exist
   and have one.
2. `add_nrt_monitoring_section`. Pass `days` when the user named a period
   (the alert window, counted back from today; default 90, max 365).
3. Report what the tool message says was built, including the period.

# Do not pre-fetch

Do **not** run `pick_dataset`, `pull_data`, `generate_insights` or
`show_imagery` for this. The tool pulls the alert data, builds the chart,
resolves the map layer and builds the mosaic itself. Running those first
duplicates the work and leaves stray widgets and insights behind.

# What to tell the user

- **It takes a while** — a data pull, a satellite scene search and a written
  summary. Say what you are doing before you call it, and do not call it
  twice while waiting.
- **Satellite imagery is optional.** Areas too large for a mosaic (bigger
  than about 50,000 km², so most countries) and periods with no clear scenes
  yield a two-widget section. The tool message says so; pass that on rather
  than retrying or apologising for it.
- **The section is read-only** once built — see the `dashboard` skill. To
  change one, delete it and build another. The tool refuses to build a second
  section for a period the dashboard already covers.
- Alerts are **potential** disturbance, not confirmed deforestation. The
  section's own description says this; do not contradict it.
