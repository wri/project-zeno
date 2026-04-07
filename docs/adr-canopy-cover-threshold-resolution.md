# ADR: Deterministic Canopy Cover Threshold Resolution

**Date:** 2026-04-06
**Status:** Accepted
**Branch:** feat/canopy-cover-threshold
**PR:** wri/project-zeno#597

---

## Context

Tree cover loss datasets on Global Forest Watch support a `canopy_cover` threshold
parameter (valid values: 10, 15, 20, 25, 30, 50, 75%) that filters which pixels
are counted as "forest". Different countries define forest using different minimum
canopy densities in their national legislation and UNFCCC submissions.

The previous implementation encoded the country→threshold mapping as a large
`TREE COVER THRESHOLD SELECTION` block inside the base system prompt. This block
listed ~30 countries and their thresholds and instructed the LLM to infer the
correct threshold from the query context and pass it as the `canopy_cover`
argument to `pull_data`.

### Problems

1. **System prompt bloat.** The block was sent with every query, regardless of
   whether tree cover analysis was involved. This increases token cost and
   prompt complexity for all queries (raised by @yellowcap and @soumya).

2. **LLM inference is unreliable.** Threshold selection based on country context
   is a deterministic lookup; delegating it to LLM inference introduces
   non-determinism and occasional errors.

3. **Maintenance coupling.** Adding a new country required editing the system
   prompt, touching a high-traffic file with broad blast radius.

4. **Separation of concerns.** The base system prompt is meant to describe the
   agent's workflow and tools, not to encode dataset-specific lookup tables.

---

## Decision

Move the country→threshold mapping out of the system prompt and into a dedicated
Python module (`src/agent/tools/canopy_cover.py`). Apply the mapping
deterministically at data fetch time inside `pull_data`, using the country AOI
already stored in state.

### Resolution priority

```
1. Explicit user override  →  user said "use 20% canopy cover"
2. Country lookup          →  first gadm country-level AOI in state["aoi_selection"]
3. GFW default             →  30%
```

Only country-level (`subtype="country"`, `source="gadm"`) AOIs are matched.
Sub-national AOIs (states, districts) and non-gadm sources (wdpa, kba, landmark)
fall through to the GFW default.

### System prompt change

The 27-line `TREE COVER THRESHOLD SELECTION` block was removed entirely. No
replacement was needed — the `pull_data` tool docstring already instructs the LLM
to only set `canopy_cover` when the user explicitly requests a threshold. A
system prompt note on top would have been redundant.

### Citation and justification in responses

The citation language ("10% — India's national forest definition per the
[Forest Survey of India (FSI)](https://fsi.nic.in/)") has always lived in
`presentation_instructions` inside `tree_cover_loss.yml`. This is unchanged.
`presentation_instructions` is injected only by `generate_insights` when the
Tree Cover Loss dataset is active — it is never in the base system prompt.

### Files changed

| File | Change |
|------|--------|
| `src/agent/tools/canopy_cover.py` | **New.** Lookup table + `resolve_canopy_cover()` |
| `src/agent/tools/pull_data.py` | Uses `resolve_canopy_cover()` instead of `canopy_cover or 30` |
| `src/agent/graph.py` | Removed 27-line system prompt block |
| `tests/tools/test_canopy_cover_lookup.py` | **New.** Unit tests for lookup table and resolver |

---

## Consequences

### Positive

- **Cheaper and simpler.** ~25 lines removed from the base system prompt; every
  query saves those tokens regardless of dataset.
- **Deterministic.** Country→threshold mapping is a pure function; identical
  inputs always produce identical outputs with no LLM inference step.
- **Easier to extend.** Adding a new country means adding one dict entry to
  `COUNTRY_THRESHOLDS` — no prompt editing required.
- **Better separation of concerns.** System prompt describes workflow; dataset
  YAML describes presentation; Python code handles data logic.

### Trade-offs

- **Only country-level AOIs are auto-resolved.** Sub-national queries (e.g.,
  "show deforestation in Maharashtra") default to 30% even though India's
  national threshold is 10%. The user can still override explicitly. This is a
  known limitation and can be improved by adding parent-country resolution later.
- **Unknown countries default to 30%.** Any country not in `COUNTRY_THRESHOLDS`
  silently uses the GFW default. The table covers the countries listed in the
  original system prompt; gaps should be filled as new country support is added.
- **Explicit overrides still go through the LLM.** The `canopy_cover` parameter
  on `pull_data` remains LLM-settable for cases where the user explicitly names
  a threshold. The system prompt note keeps the LLM aware of this path.
