---
name: analysis-templates
description: Build a curated analysis section on a dashboard — a chart, its map layers and the words that go with them, for one area and one period, in one step.
when_to_use: User asks to monitor or watch an area, asks for recent/near-real-time disturbance on a dashboard, or asks to refresh or change what a curated section covers. Not for a one-off look at data without a dashboard — use `analyze`, or `show-imagery` for imagery alone.
requires: add_analysis_section, refresh_analysis_section, reconfigure_analysis_section, send_nudge, create_dashboard, pick_aoi, inspect_view_context
---

# Curated analysis sections

An **analysis template** builds a whole dashboard section in one call: a
chart, the map layers that belong with it, and a title and description
written from the data. `add_analysis_section(template, params?)` runs one.

It is not like the other dashboard tools. They snapshot work the
conversation already did; a template does the work itself.

Three verbs, because they are three different asks:

| The user says | Tool | Confirm first? |
|---|---|---|
| "monitor this area" | `add_analysis_section` | no |
| "refresh it", "anything new?" | `refresh_analysis_section` | no |
| "show me 3 months instead" | `reconfigure_analysis_section` | **yes** |

# Steps

1. The dashboard: reuse the one the user is viewing or made earlier this
   conversation. If there is none, `pick_aoi` then `create_dashboard` — the
   section covers the dashboard's own area, so the dashboard has to exist
   and have one.
2. `add_analysis_section` with the template that fits the request. Pass
   `params` only when the user named something specific, e.g.
   `{"days": 30}`; leave it out for the template's own defaults, which are
   the right answer otherwise. Each template's parameters are listed below.
3. Report what the tool message says was built, including the period.

# Do not pre-fetch

Do **not** run `pick_dataset`, `pull_data`, `generate_insights` or
`show_imagery` for a template. It pulls its own data, builds its own chart,
resolves its own map layers and writes its own words. Running those first
duplicates the work and leaves stray widgets and insights behind.

# Bringing a section up to date ("refresh it", "anything new since?")

`refresh_analysis_section(section?)` runs the section again with the
parameters it already has, so it shows today's data. The same question,
asked again now.

It takes **no parameters** and needs **no confirmation**: the user asked for
exactly this, and nothing about what the section covers changes.

# Changing what a section covers ("show me the last 3 months instead")

`reconfigure_analysis_section(params, confirmed, section?)` rebuilds the
section for different parameters. That is a different question from the one
on screen, and the previous answer is gone afterwards.

**Confirm before you apply it.** So:

1. Call `send_nudge` with the options that fit what they asked — for a
   period, `send_nudge(nudge_type="time_range_choice", options=["Last 2
   weeks", "Last 30 days", "Last 90 days"])` — and wait for their answer.
2. Then call `reconfigure_analysis_section(params={...}, confirmed=True)`.

`confirmed=True` means "the user has told me what they want". Set it only
when they have: either they answered your nudge, or they named it exactly in
the same breath as the request ("change it to the last 30 days"), which *is*
their answer — nudge then only if it is unclear which section or which value
they mean. Never set it on a request that names nothing ("can I see more
history?"); ask first.

If you pass a parameter a template does not take, the tool says so and lists
what it does take. Read that and retry rather than guessing again.

Never reach for `add_analysis_section` to change a section — that builds a
second one next to the first.

# What to tell the user

- **It takes a while** — a data pull, sometimes a satellite scene search,
  and a written summary. Say what you are doing before you call it, and do
  not call it twice while waiting.
- **The section's content is read-only** once built — see the `dashboard`
  skill. Rebuilding the whole section is the exception, through the two
  tools above. Anything else means deleting it and building another. A
  template refuses to build a second section identical to one already
  there; refresh that one instead.
- **A widget can be missing.** The tool message says what was not
  available and why; pass that on rather than retrying or apologising.

# The templates

## `nrt-monitoring` — near-real-time monitoring

Three widgets for the dashboard's area: a chart of integrated disturbance
alerts over the period, a map of those alerts, and satellite imagery of the
same area and period.

- Parameters: `days`, the alert window counted back from today. **Default
  14** — the last two weeks — maximum 365. So `{"days": 90}` for a quarter.
- Satellite imagery is optional. Areas too large for a mosaic (bigger than
  about 50,000 km², so most countries) and periods with no clear scenes
  yield a two-widget section.
- Alerts are **potential** disturbance, not confirmed deforestation. The
  section's own description says this; do not contradict it.
