---
name: analyze
description: Full pipeline — resolve AOI, pick dataset, pull data, generate chart insight.
when_to_use: User asks a question that needs data to answer: analysis, charts, insights, comparisons across places or time, or "which/what/where/how many" fact-finding over real data (e.g. "analyze", "show a chart", "which district had the most deforestation", "compare X across regions"). Not when they only say pull/fetch/get data without asking a data-driven question — use `pull-data` instead.
requires: pick_aoi, pick_dataset, pull_data, generate_insights
---

# Workflow

1. `pick_aoi` — pass the user's request describing the place; the geocoder extracts, translates and resolves the AOI (and any subregion) on its own.
2. `pick_dataset` — choose dataset and date range. Its tool description covers re-picking when the user changes topic or context layer. If it returns no dataset, **or only suggested/alternative datasets**, stop and relay its explanation and the alternatives to the user — do not proceed to `pull_data`, and do not pick one of the suggestions yourself. Wait for the user to choose.
3. `pull_data` — fetch data for AOI + dataset + dates. You need AOI, dataset, and a date range before this step. Set `change_over_time_query=True` when the user asks about change/transition/dynamics between the dates (e.g. "transition", "shift", "converted to/from"); leave it `False` for a composition/snapshot question about one point in time. Getting this wrong on the Global land cover dataset pulls a single-year snapshot instead of the 2015→2024 transition matrix, so the data can't answer the question.
4. `search_blogs` (optional) — when WRI published context would strengthen the insight, read skill `wri-insights`, call `search_blogs`, then give the **intermediate message** with blog links (see skill `wri-insights`). Call **after** pull, **before** generate.
5. `generate_insights` — after a successful pull, always run this to produce one chart insight.

Call tools **one at a time**, never in parallel. Provide short progress messages between tool calls; after `search_blogs`, the next message to the user **must** be the WRI findings summary with links before the next tool.

# Requirements

- This workflow applies only when the user wants full analysis. For dataset-only or AOI-only requests, use the matching skill instead — do not ask for a location or run later steps.
- AOI + dataset + date range are required before `pull_data`. If the user gave a place but AOI is missing, resolve it. If dates are omitted, `pick_dataset` supplies defaults.
- If pull fails or data is unavailable, inform the user and **stop** — do not call further tools.
- After pulling data, always create new insights (do not skip `generate_insights`).

# Relative dates

Compute `start_date` / `end_date` from the session date in the system prompt when the user says e.g. "last ten years" or "past 3 months".
