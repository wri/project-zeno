---
name: explore
description: Discover what datasets and coverage exist for an area before committing to a full analysis.
when_to_use: User asks "what data do you have for X?", "what's available in Y?", or otherwise wants a preview rather than a finished chart.
---

# Workflow

1. Resolve the AOI with `geo_subagent(query)` if a place is named. Skip if the question is purely catalogue-level.
2. Call `list_datasets()` (empty query) or `list_datasets("topic")` to surface candidate datasets.
3. Optionally `fetch(aoi_refs, dataset_id, ...)` for the top candidate and call `execute("df.describe()", [stat_id])` to give the user a sense of coverage and magnitude.
4. Reply with a short bulleted summary. Do not produce a chart artifact for this skill — exploration is a text reply.

# Notes

- Keep replies tight. Three to five bullets max.
- If you fetch sample data, mention the date range you used so the user can refine.
