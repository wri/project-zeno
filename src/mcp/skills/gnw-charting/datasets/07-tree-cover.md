# Tree cover (dataset 7)

Tree cover (2000). Tree canopy cover density (percent) in the year 2000 at 30 m for vegetation over 5 m tall. Gives tree cover area and density for 2000, with a selectable canopy cover threshold; can be limited to primary forest. One year only, no change over time.

Dates: 2000-01-01 to 2000-12-31.

## Columns

The columns of `rows.csv` and of `pull_data`'s rows, as the GNW analytics API returns them.

| Column | Type | Unit | Holds |
|---|---|---|---|
| `aoi_id` | string |  | The area's id at the analytics API: a GADM id without its version suffix (BRA.14 for gadm:BRA.14_1), or the source's id. |
| `aoi_type` | string |  | The kind of area: admin, protected_area, key_biodiversity_area or indigenous_land. |
| `area_ha` | number | ha | Area. |
| `name` | string |  | The area's name, added by GNW. |

## Curated charts

`curated_charts` draws these with `TreeCoverChartGenerator` ([generators/tree_cover.py](../generators/tree_cover.py)).

Tree cover extent per area of interest as a bar chart.

## How to chart it

GNW's rules for this dataset, written for the code that draws GNW's own charts.

CHART TYPES: - Tree cover area by canopy-density bin → bar chart or pie chart - Values MUST be area in hectares (ha), NOT percentages or proportions DATA RULES: - Year 2000 data only — single snapshot - Exclude rows where area_ha = 0 (and note that exclusion has happened) - All areas in hectares (ha) — do NOT convert to percentages DO/DON'T: - Do NOT use the term "forest" unless primary_forest or intact_forest variable is active —
  use "tree cover" instead
- This is a SINGLE YEAR (2000) snapshot — do NOT attempt timeseries - Cannot assess pixel-level percent changes (gains/losses) TEMPORAL CONSTRAINT: - If user asks about change, trends, or temporal patterns: you MUST include ALL of:
  (a) State that this dataset cannot show change — it is a single year 2000 snapshot
  (b) Recommend Tree Cover Loss and Tree Cover Gain datasets by name
  (c) This recommendation is REQUIRED, not optional

## How to present it

This is a year 2000 baseline snapshot — clarify the date to users. Use "tree cover" not "forest" unless primary forest or IFL layer is active. Tree cover includes plantations, not just natural forest. For change analysis, direct to Tree Cover Loss or Tree Cover Gain datasets.

## Cautions

For the purpose of this study, "tree cover" was defined as all vegetation taller than 5 meters in height. "Tree cover" is the biophysical presence of trees and may take the form of natural forests or plantations existing over a range of canopy densities.

## Options (pull_data)

- context layer `primary_forest`: Shows loss within humid tropical primary forest in global pan-tropical regions
- `canopy_cover`, one of [10, 15, 20, 25, 30, 50, 75]: Minimum percent each 30m pixel is covered by forest canopy in year 2000 to count as a forest.

## Colors (use these, do not invent others)
- single series: #97BD3D

## Citation

Use the following credit when these data are displayed: Source: Hansen/UMD/Google/USGS/NASA, accessed through Global Forest Watch Use the following credit when these data are cited: Hansen, M. C., P. V. Potapov, R. Moore, M. Hancher, S. A. Turubanova, A. Tyukavina, D. Thau, S. V. Stehman, S. J. Goetz, T. R. Loveland, A. Kommareddy, A. Egorov, L. Chini, C. O. Justice, and J. R. G. Townshend. 2013. "High-Resolution Global Maps of 21st-Century Forest Cover Change." Science 342 (15 November): 850-53. Data available on-line from: [UMD Tree Cover Data](https://glad.umd.edu/dataset/global-2010-tree-cover-30-m). Accessed through Global Forest Watch on <date>. [www.globalforestwatch.org](https://www.globalforestwatch.org)
