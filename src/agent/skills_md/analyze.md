---
name: analyze
description: Full pipeline — resolve AOI, pick dataset, pull data, generate chart insight.
when_to_use: User wants end-to-end analysis with a chart or insight (e.g. "analyze", "show a chart"). Not when they only say pull/fetch/get data — use `pull-data` instead.
---

# Workflow

1. `pick_aoi` — resolve place(s). See skill `pick-aoi` for subregion and translation rules.
2. `pick_dataset` — choose dataset and date range. See skill `pick-dataset` if the user changes topic or context layer.
3. `pull_data` — fetch data for AOI + dataset + dates. You need AOI, dataset, and a date range before this step.
4. `wri_insights` (optional) — when WRI published context would strengthen the insight, read skill `wri-insights`, call `wri_insights`, then give the **intermediate message** with blog links (see skill `wri-insights`). Call **after** pull, **before** generate.
5. `generate_insights` — after a successful pull, always run this to produce one chart insight.

Call tools **one at a time**, never in parallel. Provide short progress messages between tool calls; after `wri_insights`, the next message to the user **must** be the WRI findings summary with links before the next tool.

# Requirements

- This workflow applies only when the user wants full analysis. For dataset-only or AOI-only requests, use the matching skill instead — do not ask for a location or run later steps.
- AOI + dataset + date range are required before `pull_data`. If the user gave a place but AOI is missing, resolve it. If dates are omitted, `pick_dataset` supplies defaults.
- Be proactive: warn on imperfect place/date/dataset matches but continue when reasonable.
- If pull fails or data is unavailable, inform the user and **stop** — do not call further tools.
- After pulling data, always create new insights (do not skip `generate_insights`).
- If you used `wri_insights`, send the intermediate summary with links **before** `generate_insights`, and end the final reply with affirmative sentence(s) linking to those blog posts (see skill `wri-insights`).

# Relative dates

Compute `start_date` / `end_date` from the session date in the system prompt when the user says e.g. "last ten years" or "past 3 months".
