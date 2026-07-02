---
name: dashboard
description: Create a dashboard for an area and fill it with insights (new or recalled).
when_to_use: User asks to build/create a dashboard for a place, or to add an insight/analysis to a dashboard. Not for one-off analysis without a dashboard — use `analyze`.
requires: create_dashboard, add_to_dashboard
---

# Dashboards

A dashboard is a persistent collection of insights for ONE area (a country, a
state, a protected area). Widgets reference insights that already exist —
adding to a dashboard never recomputes anything.

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

# Composing ("build me a dashboard for X about A, B, C")

1. `pick_aoi` for X (skip if already selected), then `create_dashboard`.
2. Per topic, reuse existing work before computing: if the user refers to an
   earlier finding, `search_insights` → `add_to_dashboard`. Otherwise run the
   `analyze` pipeline (pick_dataset → pull_data → generate_insights) →
   `add_to_dashboard`.
3. Give a short progress message per topic added.

# Adding a single insight ("add this to my dashboard")

`add_to_dashboard` — it defaults to the current insight in state and the
dashboard in state/on screen. Recall the insight first (`search_insights`)
only if the user refers to a past finding that is not the current one.

# Stop conditions

- Add only what the user asked for — never keep adding widgets unprompted.
- After the requested widgets are added, confirm what the dashboard now
  contains and stop. Suggest at most one follow-up topic; do not run it.
- If a step fails (no data, insight not found), report it and continue with
  the remaining topics rather than aborting the whole dashboard.
