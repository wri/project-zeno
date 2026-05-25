---
name: fao-fra
description: National-scale FAO Forest Resources Assessment 2025 statistics for any country — forest area, carbon, biomass, growing stock, ownership, management, disturbances, fire, restoration. The `pick_fra_variable` subagent enumerates the exact variables.
when_to_use: User asks about country-reported / officially-reported / FAO forest statistics, total national forest area, nationally-reported carbon stock or biomass, forest ownership or management categories, area affected by fire / pests / disease, degraded forest, or forest restoration. Not for sub-national analysis or custom date ranges — use `analyze` or `pull-data` for those.
---

# Workflow

1. `pick_aoi` — pass the user's request verbatim. The geocoder resolves the place; for FAO data the resolved AOI MUST be country-level GADM (`subtype=country`). One or more countries is fine.
2. `pick_fra_variable` — pass the user's request verbatim. The subagent picks exactly one FAO FRA variable (e.g. `forest_area`, `carbon_stock`, `ownership`). Read the chosen variable name from its ToolMessage.
3. `query_fra_data(variable=...)` — pass the variable name from step 2. Country ISO3 codes come from the AOI selection automatically. Add `year=` only if the user asked for a specific reporting year.
4. `generate_insights` — produce one chart insight from the pulled FAO statistics.

Call tools **one at a time**, never in parallel.

# Capability limits

- **Country-level only.** FAO FRA 2025 carries national aggregates. If `pick_aoi` returns a sub-national area (state, district, KBA, WDPA, custom geometry), `query_fra_data` will redirect — when this happens, tell the user FAO data is country-only and offer the `analyze` skill (GFW remote-sensing) for sub-national questions.
- **Fixed reporting years.** Data exists only for 1990, 2000, 2010, 2015, 2020, 2025. Do not promise continuous time-series. If the user asks for an arbitrary date range, explain the limitation and either drop to the nearest reporting year or redirect to `analyze`.
- **One variable per call.** If the user asks about multiple unrelated FAO variables (e.g. "carbon and ownership"), run the recipe twice — once per variable.

# Wording

- Use "forest area change" or "net forest loss/gain" — **never** call FAO net change "deforestation". Net change = deforestation minus expansion.
- FAO's "forest" definition differs from GFW/Hansen "tree cover" — do not compare or combine figures across the two datasets in the same answer or chart.
- Note that FRA data is country-reported (not satellite-derived) when relevant.
- Do not interpolate between reporting years; do not compare across FRA editions (each edition is independent).

# Citations

The dataset's official citation (DOI) is added automatically per the orchestrator policy (from `state["dataset"]["citation"]`). In addition, link to the [FAO FRA Data Explorer](https://fra-data.fao.org) when pointing the user at where to browse more data for the same country or variable. The [FAO Global Forest Resources Assessment programme page](https://www.fao.org/forest-resources-assessment) is optional context — include it when the user asks about methodology or coverage rather than specific numbers.

# Routing back out

Exit to `analyze` (or `pull-data`) when the AOI is sub-national, the user wants a custom date range, or the request is pixel-level / near-real-time disturbance — FRA only covers country-level fixed reporting years.
