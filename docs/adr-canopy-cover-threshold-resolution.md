# ADR: Deterministic Canopy Cover Threshold Resolution

**Date:** 2026-04-07
**Status:** Accepted
**Branch:** feat/canopy-cover-threshold
**PR:** wri/project-zeno#597

---

## Context

Tree cover loss datasets on Global Forest Watch support a `canopy_cover` threshold
parameter (valid values: 10, 15, 20, 25, 30, 50, 75%) that filters which pixels
are counted as "forest". The GFW default is 30%, but different countries define
forest using different minimum canopy densities in their national legislation and
UNFCCC submissions (e.g. India uses 10% per FSI, Australia uses 20% per ABARES,
Chile uses 25% per CONAF).

The baseline agent always used 30%. This branch adds country-specific threshold
selection so that queries about a known country automatically use the appropriate
national forest definition.

---

## Options Considered

### Option A — System prompt instruction (rejected)

Encode the country→threshold mapping as a section in the base system prompt and
instruct the LLM to infer the correct threshold from the query context, passing it
as the `canopy_cover` argument to `pull_data`.

**Problems:**
- **Token cost.** The block is sent with every query, regardless of whether tree
  cover analysis is involved.
- **System prompt bloat.** Dataset-specific lookup tables have no place in a prompt
  that is meant to describe the agent's workflow. Gradual accumulation of similar
  blocks will degrade quality and increase cost over time (raised by @soumya and
  @yellowcap).
- **Non-determinism.** Threshold selection is a pure lookup; delegating it to LLM
  inference introduces occasional errors with no easy way to test or audit.
- **Maintenance coupling.** Adding a country means editing the system prompt — a
  high-traffic file with broad blast radius.

### Option B — Deterministic code lookup (selected)

Encode the country→threshold mapping in a dedicated Python module. Resolve the
threshold deterministically at data fetch time inside `pull_data`, using the
country AOI already stored in state from `pick_aoi`.

---

## Decision

Option B. The mapping lives in `src/agent/tools/canopy_cover.py` as a typed dict
keyed on ISO 3166-1 alpha-3 country codes. `resolve_canopy_cover()` applies the
following priority at call time:

```
1. Explicit user override  →  user said "use 20% canopy cover"
2. Country lookup          →  ISO3 src_id from first gadm country-level AOI in state
3. GFW default             →  30%
```

The base system prompt is unchanged — the `pull_data` tool docstring is sufficient
to instruct the LLM to only pass `canopy_cover` when the user explicitly names a
threshold.

### Citation and justification in responses

The citation language ("10% — India's national forest definition per the
[Forest Survey of India (FSI)](https://fsi.nic.in/)") lives in
`presentation_instructions` inside `tree_cover_loss.yml`. This is injected by
`generate_insights` only when the Tree Cover Loss dataset is active — never in the
base system prompt. This is unchanged.

### Files changed

| File | Change |
|------|--------|
| `src/agent/tools/canopy_cover.py` | **New.** Typed lookup table + `resolve_canopy_cover()` |
| `src/agent/tools/pull_data.py` | Calls `resolve_canopy_cover()` instead of `canopy_cover or 30` |
| `src/agent/graph.py` | Removed 27-line `TREE COVER THRESHOLD SELECTION` block |
| `tests/tools/test_canopy_cover_lookup.py` | **New.** Unit tests for lookup table and resolver |

---

## Consequences

### Positive

- **Cheaper.** ~25 lines removed from the base system prompt; token savings on
  every query regardless of dataset.
- **Deterministic and testable.** Country→threshold mapping is a pure function
  with a full unit test suite.
- **Easier to extend.** Adding a country is one dict entry in `canopy_cover.py`;
  no prompt editing required.
- **Better separation of concerns.** System prompt describes workflow; dataset YAML
  describes presentation; Python code handles data logic.

### Trade-offs

- **Sub-national AOIs are not yet auto-resolved.** Needs to be confirmed with the
  reserach team before proceeding. A query for "Maharashtra, India" will currently
  default to 30% rather than India's 10%.
  This is trivial to fix: GADM `src_id` values for sub-national units encode
  the ISO3 prefix (e.g. `"IND.12_1"`), so extracting `src_id.split(".")[0]` would
  cover all GADM admin levels without any DB lookup. Left as a follow-up.
- **Non-gadm sources default to 30%.** Protected areas (wdpa), Key Biodiversity
  Areas (kba), and indigenous lands (landmark) have no country code in their
  `src_id`. A DB lookup would be required to resolve the parent country.
- **Unknown countries default to 30%.** Countries not in `COUNTRY_THRESHOLDS`
  silently use the GFW default. The table covers the countries from the original
  system prompt; gaps should be filled incrementally.
- **Explicit overrides still go through the LLM.** The `canopy_cover` parameter
  on `pull_data` remains LLM-settable for cases where the user explicitly names a
  threshold.
