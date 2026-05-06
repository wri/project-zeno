---
name: analyze
description: Full analysis pipeline from a single user prompt — resolve place, pick dataset, fetch data, produce a chart artifact.
when_to_use: User asks a complete question from scratch, e.g. "analyze deforestation in Para" or "show forest loss for the Amazon since 2020".
---

# Workflow

1. Call `geo_subagent(query)` with the place phrase from the user. Use the returned `aoi_refs` for every later step.
2. Call `list_datasets(query)` with a short topical phrase derived from the user's intent (e.g. "tree cover loss", "alerts"). Pick the best id from the result.
3. Call `fetch(aoi_refs, dataset_id, start_date, end_date)`. If the user did not specify dates, pick a reasonable window from the dataset's `date_range` (most recent 1–2 years) and warn the user briefly.
4. Call `analyst_subagent(task, stat_ids=[stat_id], dataset_id, aoi_refs)`. Pass the original user question as `task`.
5. Reply with one short sentence acknowledging the produced artifact and surfacing the title; do not restate the chart contents — the artifact event already carries them.

# Notes

- Never paste raw rows into the conversation. They are in the data cache; the analyst reads them.
- If the AOI is ambiguous, pick the most prominent match and mention the assumption in the final reply.
