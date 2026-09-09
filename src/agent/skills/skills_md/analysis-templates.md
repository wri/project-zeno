---
name: analysis-templates
description: Build a curated analysis section on a dashboard — a chart, its map layers and the words that go with them, for one area and one period, in one step.
when_to_use: User asks to monitor or watch an area, asks for recent/near-real-time disturbance on a dashboard, or asks to change the time window / period / date range of a curated section. Not for a one-off look at data without a dashboard — use `analyze`, or `show-imagery` for imagery alone.
requires: add_analysis_section, update_analysis_section, send_nudge, create_dashboard, pick_aoi, inspect_view_context
---

# Curated analysis sections

An **analysis template** builds a whole dashboard section in one call: a
chart, the map layers that belong with it, and a title and description
written from the data. `add_analysis_section(template, days?)` runs one.

It is not like the other dashboard tools. They snapshot work the
conversation already did; a template does the work itself.

# Steps

1. The dashboard: reuse the one the user is viewing or made earlier this
   conversation. If there is none, `pick_aoi` then `create_dashboard` — the
   section covers the dashboard's own area, so the dashboard has to exist
   and have one.
2. `add_analysis_section` with the template that fits the request. Pass
   `days` when the user named a period; leave it out for the template's own
   default.
3. Report what the tool message says was built, including the period.

# Do not pre-fetch

Do **not** run `pick_dataset`, `pull_data`, `generate_insights` or
`show_imagery` for a template. It pulls its own data, builds its own chart,
resolves its own map layers and writes its own words. Running those first
duplicates the work and leaves stray widgets and insights behind.

# Changing the window ("show me the last 3 months instead")

`update_analysis_section(days, confirmed, section?)` moves an existing
section to a new window. The template rebuilds everything for that period
and rewrites the title and description, because they state the period.

**Confirm before you apply it.** A window change replaces every figure the
user is looking at, and the old numbers are gone afterwards. So:

1. Call `send_nudge(nudge_type="time_range_choice", options=[...])` with the
   windows that fit what they asked — e.g. `["Last 2 weeks", "Last 30 days",
   "Last 90 days"]` — and wait for their answer.
2. Then call `update_analysis_section(days=<their choice>, confirmed=True)`.

`confirmed=True` means "the user has told me which window they want". Set it
only when they have: either they answered your nudge, or they named the exact
window in the same breath as the request ("change it to the last 30 days"),
which *is* their answer — nudge then only if it is unclear which section or
which period they mean. Never set it on a request that names no window ("can
I see more history?"); ask first.

Never reach for `add_analysis_section` to change a period — that builds a
second section next to the first.

# What to tell the user

- **It takes a while** — a data pull, sometimes a satellite scene search,
  and a written summary. Say what you are doing before you call it, and do
  not call it twice while waiting.
- **The section's content is read-only** once built — see the `dashboard`
  skill. Its period is the exception: `update_analysis_section` moves it.
  Anything else means deleting it and building another. A template refuses
  to build a second section for a period the dashboard already covers.
- **A widget can be missing.** The tool message says what was not
  available and why; pass that on rather than retrying or apologising.

# The templates

## `nrt-monitoring` — near-real-time monitoring

Three widgets for the dashboard's area: a chart of integrated disturbance
alerts over the period, a map of those alerts, and satellite imagery of the
same area and period.

- `days` is the alert window counted back from today. **Default 14** — the
  last two weeks — maximum 365.
- Satellite imagery is optional. Areas too large for a mosaic (bigger than
  about 50,000 km², so most countries) and periods with no clear scenes
  yield a two-widget section.
- Alerts are **potential** disturbance, not confirmed deforestation. The
  section's own description says this; do not contradict it.
