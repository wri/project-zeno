---
name: pull-data
description: Fetch data for a place and dataset — no chart or insight unless the user asks.
when_to_use: User asks to pull, fetch, or get data (with place and/or topic). Not for full analysis, charts, or "analyze" requests — use skill `analyze` only when they want a chart/insight.
---

# Pull-only requests

When the user wants data retrieved but does **not** ask for analysis, a chart, or insights (e.g. "pull dist alerts in Bern for last 2 weeks", "fetch tree cover loss for Para"):

1. `pick_aoi` — pass the user's request describing the place; the geocoder extracts, translates and resolves the AOI (and any subregion) on its own.
2. `pick_dataset` — choose dataset and date range. Dataset-only/re-pick rules are in its tool description. If it returns no dataset, stop and relay its explanation to the user — do not proceed to `pull_data`.
3. `pull_data` — fetch data for AOI + dataset + dates.
4. **Stop.** Confirm what was pulled. Do **not** call `generate_insights`.

Do **not** read skill `analyze` for pull-only requests — that skill always runs insights after pull.

# Requirements

- AOI + dataset + date range are required before `pull_data`. If the user gave a place but AOI is missing, resolve it. If dates are omitted, `pick_dataset` supplies defaults.
- If pull fails or data is unavailable, inform the user and stop.
- Call tools **one at a time**, never in parallel.

# Relative dates

Compute `start_date` / `end_date` from the session date in the system prompt when the user says e.g. "last 2 weeks" or "past 3 months".

# When to run insights

Call `generate_insights` only if the user explicitly asks for analysis, a chart, visualization, or insights — or uses wording like "analyze", "show me a chart", "what does the data show".
