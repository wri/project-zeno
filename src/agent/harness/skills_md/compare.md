---
name: compare
description: Side-by-side comparison across multiple AOIs or multiple datasets.
when_to_use: User asks "compare X vs Y", "which is higher A or B", or otherwise requests a comparison.
---

# Workflow

1. Resolve each AOI separately with `geo_subagent(query)`. Keep one `aoi_refs` list per side of the comparison.
2. Pick the dataset with `list_datasets(query)`. Use the same dataset for every side unless the user explicitly requests cross-dataset comparison.
3. Call `fetch(...)` once per side with the same date range. Collect every returned `stat_id`.
4. Call `analyst_subagent(task, stat_ids=[all_stat_ids], dataset_id, aoi_refs=[all_aoi_refs])`. The task string should explicitly mention "compare" so the analyst groups the result.
5. Reply with one short sentence summarising the comparison; do not restate per-AOI numbers — the artifact carries them.

# Notes

- If the user asks "compare A vs B" but only resolves to one AOI, ask a clarifying question rather than fabricating a second region.
