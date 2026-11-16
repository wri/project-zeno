---
name: analyze
description: Full pipeline — resolve AOI, pick dataset, pull data, generate chart insight.
when_to_use: User wants end-to-end analysis with a chart or insight (e.g. "analyze", "show a chart"). Not when they only say pull/fetch/get data — use `pull-data` instead.
requires: pick_aoi, pick_dataset, pull_data, generate_insights
---

# Workflow

1. `pick_aoi` — pass the user's request describing the place; the geocoder extracts, translates and resolves the AOI (and any subregion) on its own.
2. `pick_dataset` — choose dataset and date range. Its tool description covers re-picking when the user changes topic or context layer. If it returns no dataset, **or only suggested/alternative datasets**, stop and relay its explanation and the alternatives to the user — do not proceed to `pull_data`, and do not pick one of the suggestions yourself. Wait for the user to choose.
3. `pull_data` — fetch data for AOI + dataset + dates. You need AOI, dataset, and a date range before this step.
<!-- flag: curated-charts-first -->
   If the user names a period ("from 2020 to 2024", "in 2019", "the last five years"), send that period to `pull_data` as `start_date` and `end_date`. The chart then shows only that period, and its total is the total of that period.
<!-- end flag -->
4. `search_blogs` (optional) — when WRI published context would strengthen the insight, read skill `wri-insights`, call `search_blogs`, then give the **intermediate message** with blog links (see skill `wri-insights`). Call **after** pull, **before** generate.
<!-- no flag: curated-charts-first -->
5. `generate_insights` — after a successful pull, always run this to produce one chart insight.
<!-- end flag -->
<!-- flag: curated-charts-first -->
5. `generate_insights` — after a successful pull, always run this to produce one chart insight. Select the `chart` argument:
   - `chart="standard"` (the default): for a first analysis of an area and a dataset, and when you are not sure. The tool shows the standard chart of the dataset when one fits the pull. When none fits, it draws a custom chart.
   - `chart="custom"`: only when the user asks for something that the standard chart does not have: a ranking or a comparison of areas, a different time step, a calculation across two datasets, a derived metric (an average, a median, a rate per year, a moving average, a cumulative total, or a figure for a part of the period), or a change that `update_insight_display` cannot make.

   After a standard chart, answer from the rows and facts in the tool message. Copy the figures; do not calculate new ones. The facts give the total, the largest and the smallest value, and the change from the first to the last year with its percent. If the pulled period is not the period that the user asked for, say so, and do not add or remove years yourself. If they do not answer the question, tell the user what the chart shows, and tell them that they can ask for more detail or for a custom chart. Do not call `generate_insights` again in the same turn. You can offer a custom chart in one short sentence; do not repeat the offer in each turn.
<!-- end flag -->

Call tools **one at a time**, never in parallel. Provide short progress messages between tool calls; after `search_blogs`, the next message to the user **must** be the WRI findings summary with links before the next tool.

# Requirements

- This workflow applies only when the user wants full analysis. For dataset-only or AOI-only requests, use the matching skill instead — do not ask for a location or run later steps.
- AOI + dataset + date range are required before `pull_data`. If the user gave a place but AOI is missing, resolve it. If dates are omitted, `pick_dataset` supplies defaults.
- If pull fails or data is unavailable, inform the user and **stop** — do not call further tools.
- After pulling data, always create new insights (do not skip `generate_insights`).
- **Standard-charts-only datasets** (the session block marks them "standard charts only"): call `generate_insights` once for one area, then only tell the user the charts are shown. Never interpret their data: no numbers, trends, rankings, comparisons, causes, or judgements. Politely decline requests for figures, comparisons of areas, custom charts, or chart changes, and say that only the standard charts are available. You may repeat the dataset's description, methodology, cautions, and citation.

# Relative dates

Compute `start_date` / `end_date` from the session date in the system prompt when the user says e.g. "last ten years" or "past 3 months".
