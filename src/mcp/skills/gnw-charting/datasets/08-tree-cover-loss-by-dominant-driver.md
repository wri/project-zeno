# Tree cover loss by dominant driver (dataset 8)

Tree cover loss by dominant driver (2001-2025). Splits tree cover loss into its direct causes: permanent agriculture, hard commodities (mining, energy), shifting cultivation, logging, wildfire, settlements and infrastructure, other natural disturbances. Gives the area and share of loss for each cause. One total for the whole period; no year-by-year values.

Dates: 2001-01-01 to 2025-12-31.

## Columns

The columns of `rows.csv` and of `pull_data`'s rows, as the GNW analytics API returns them.

| Column | Type | Unit | Holds |
|---|---|---|---|
| `aoi_id` | string |  | The area's id at the analytics API: a GADM id without its version suffix (BRA.14 for gadm:BRA.14_1), or the source's id. |
| `aoi_type` | string |  | The kind of area: admin, protected_area, key_biodiversity_area or indigenous_land. |
| `tree_cover_loss_driver` | string |  | The dominant driver of the loss. |
| `area_ha` | number | ha | Area. |
| `carbon_emissions_MgCO2e` | number | MgCO2e | Greenhouse gas emissions from the loss. |
| `name` | string |  | The area's name, added by GNW. |

## Curated charts

`curated_charts` draws these with `TCLByDriverChartGenerator` ([generators/tcl_by_driver.py](../generators/tcl_by_driver.py)).

Tree cover loss area per driver as a pie, excluding unknown drivers.

## How to chart it

CHART TYPES: - Driver breakdown → pie chart or table ONLY - DO NOT attempt a timeseries — this is a single-period aggregate (2001-2025) DATA RULES: - Exclude the "Unknown" driver class from analysis - Show area_ha or emissions (MgCO2e) per driver class for the full period 2001-2025 - 7 driver classes:
  1. Permanent agriculture — long-term, permanent tree cover loss for agriculture
  2. Hard commodities — loss due to mining or energy infrastructure
  3. Shifting cultivation — small/medium-scale temporary cultivation, later abandoned
  4. Logging — forest management within managed/natural/semi-natural forests and plantations
  5. Wildfire — fire with no visible human conversion afterward
  6. Settlements and infrastructure — roads, urban areas, built infrastructure
  7. Other natural disturbances — non-fire natural disturbances (landslides, insects, rivers)
DO/DON'T: - DO NOT use "deforestation" — use "tree cover loss" - If user asks for annual timeseries, REFUSE and suggest base "Tree cover loss" dataset - Common groupings to apply where relevant:
  Deforestation proxy: permanent agriculture + hard commodities + settlements & infrastructure
  Temporary disturbance: shifting cultivation + logging + wildfire + other natural disturbances
  All agriculture: permanent agriculture + shifting cultivation

## How to present it

Use "tree cover loss" not "deforestation." Driver = dominant driver in each ~1km cell over full period 2001-2025, not per-event attribution. Does not distinguish natural forest from plantations. Classification is an approximation — does not monitor regrowth or permanence.

## Cautions

The grouping of drivers into deforestation and temporary disturbances (i.e., likely followed by regrowth) is indicative of how these classes are defined in the data and should be considered an approximation. This product does not monitor regrowth or permanence of loss following each loss event. This product does not distinguish between the loss of natural forest and planted trees (e.g., plantations, tree crops, or agroforestry systems). While tree cover loss associated with the permanent agriculture, hard commodities, and settlements & infrastructure classes represent a close approximation of deforestation, they do not always represent the conversion of natural forests to other land uses and in some cases may represent loss of planted trees. Similarly, replacement of natural forest with wood fiber plantations is not distinguished from routine harvesting within existing plantations established before 2000, as these are both included in the logging class. These data are limited in scope to attributing drivers to tree cover loss as mapped by the Hansen et al. 2013 tree cover loss product, and therefore the detection of loss is subject to the accuracy of that product. This product shows the dominant driver in each 1 km cell over the entire period. It does not show multiple drivers if they occur in the same cell at smaller scales, nor does it detail the sequence of drivers if multiple occurred at different times within the period. A full description of limitations is included in the publication.

## Options (pull_data)

- `canopy_cover`, one of [10, 15, 20, 25, 30, 50, 75]: Minimum percent each 30m pixel is covered by forest canopy in year 2000 to count as a forest.

## Colors (use these, do not invent others)
- single series: #DC6C9A
- Logging (logging): #52A44E
- Shifting cultivation (shifting_cultivation): #E9D700
- Wildfire (wildfire): #885128
- Other natural disturbances (other_natural_disturbances): #3B209A
- Settlements & Infrastructure (settlements_infrastructure): #A354A0
- Hard commodities (hard_commodities): #E58074
- Permanent agriculture (permanent_agriculture): #E39D29
- Unknown (unknown): #D3D3D3

## Citation

Use the following credit when these data are displayed: "Tree cover loss by dominant driver". WRI/Google DeepMind. Accessed from Global Forest Watch on [Date]. [www.globalforestwatch.org](https://www.globalforestwatch.org) Use the following credit when these data are cited: Sims, M.J., R. Stanimirova, A. Raichuk, M. Neumann, J. Richter, F. Follett, J. MacCarthy, K. Lister, C. Randle, L. Sloat, E. Esipova, J. Jupiter, C. Stanton, D. Morris, C. M. Slay, D. Purves, and N. Harris. 2025. "Global Drivers of Forest Loss at 1 Km Resolution." Environmental Research Letters 20 (7): 074027. [doi:10.1088/1748-9326/add606](https://doi.org/10.1088/1748-9326/add606).
