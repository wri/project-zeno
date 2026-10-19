# Tree cover loss due to fires (dataset 10)

Tree cover loss due to fires (2001-2025). Annual tree cover loss at 30 m split into loss caused by fire and loss from all other causes. Can be limited to primary or intact forest. Time step is one year. No emissions data.

Dates: 2001-01-01 to 2025-12-31.

## Columns

The columns of `rows.csv` and of `pull_data`'s rows, as the GNW analytics API returns them.

| Column | Type | Unit | Holds |
|---|---|---|---|
| `aoi_id` | string |  | The area's id at the analytics API: a GADM id without its version suffix (BRA.14 for gadm:BRA.14_1), or the source's id. |
| `aoi_type` | string |  | The kind of area: admin, protected_area, key_biodiversity_area or indigenous_land. |
| `tree_cover_loss_year` | integer |  | The year the loss was detected. |
| `area_ha` | number | ha | Area. |
| `carbon_emissions_MgCO2e` | number | MgCO2e | Greenhouse gas emissions from the loss. |
| `tree_cover_loss_from_fires_area_ha` | number | ha | Tree cover loss caused by fire. |
| `tree_cover_loss_non_fires_area_ha` | number | ha | Tree cover loss from all other causes. |
| `name` | string |  | The area's name, added by GNW. |

## Curated charts

`curated_charts` draws these with `TCLByFiresChartGenerator` ([generators/tcl_by_fires.py](../generators/tcl_by_fires.py)).

Fire versus non-fire tree cover loss per year as a stacked bar, or a
pie of the two when only one year is in range.

## How to chart it

GNW's rules for this dataset, written for the code that draws GNW's own charts: where they say REFUSE, decline that request and say why.

CHART TYPE: If the data covers a single area of interest and contains more than one year, use a stacked bar chart with x=tree_cover_loss_year and two stacked series: tree_cover_loss_from_fires_area_ha and tree_cover_loss_non_fires_area_ha. If the data covers a single area of interest and contains only a single year or is a total across all years (one row total), use a pie chart with the same two fields as slices. If the data covers multiple areas of interest (e.g. multiple countries, regions, or locations), use a stacked bar chart with x=location/area name and keep both series so users can compare and rank fire loss across areas. Do not plot area_ha separately in either case. Rename fields before plotting: tree_cover_loss_from_fires_area_ha → "Tree cover loss due to fires", tree_cover_loss_non_fires_area_ha → "All other tree cover loss". NEVER show carbon_emissions_MgCO2e for this dataset. DATA RULES: - Drop rows where area_ha = 0 - Use 30% canopy density threshold - If primary_forest or intact_forest variable is active, filter accordingly DO/DON'T: - If neither primary_forest nor intact_forest is active, DO NOT use the term "deforestation"; use "tree cover loss" - If user asks for intra-year or seasonal breakdown, REFUSE — data is annual only - Warn about 2001-2010 vs 2011-2025 methodology difference when showing trends across both periods CHART TITLES when intact_forest is active: the metric is tree cover loss occurring INSIDE intact forest landscapes, a different measurement from the reduction of intact forest extent. Never title a chart in a way that reads as intact forest being lost — not "Intact Forest Loss", not "Intact Forests Loss", and not as a qualifier of another metric. Name the metric "Tree Cover Loss in Intact Forests". That is the metric phrase to embed, not the whole title: still include the cadence, the area of interest and the period as you normally would

## How to present it

Use "tree cover loss" rather than "deforestation" only when neither primary nor intact forest is applied as a context layer. When intact_forest is applied, "deforestation" may describe the process but never takes intact forest as its object. This measures canopy loss only; it doesn't track regrowth or permanence. Always state the canopy density threshold used (30%). Do not mention or report carbon emissions for this dataset. If trend spans 2001-2025, note the methodology change after 2010. If the primary_forest context layer is applied, prefer the concise "primary forest loss". If the intact_forest context layer is applied, do NOT use "intact forest loss" or any wording that reads as intact forest being lost: this dataset measures tree cover loss occurring *inside* intact forest landscapes, which is a different quantity from the reduction in IFL extent that the IFL dataset itself publishes. Say "tree cover loss in intact forests" or "tree cover loss within intact forest landscapes". This applies to chart titles, axis labels and prose alike, titles must use the same wording as the charts themselves, and it holds just as much when the phrase qualifies a different metric. Never name intact forest as the thing being lost, whatever the verb: not "intact forest loss", not "intact forests loss", and not "deforestation of intact forest". CHART TITLE: should reflect that the chart shows total tree cover loss split by fires vs. other causes.

## Cautions

Tree cover is defined as all vegetation greater than 5 meters in height and may take the form of natural forests or plantations across a range of canopy densities. Tree cover loss is defined as “stand replacement disturbance” which is considered to be clearing of at least half of tree cover within a 30-meter pixel. The exact threshold is variable both through space and time and is biome-dependent. This may not necessarily equate to deforestation.
This dataset does not include low-intensity and understory forest fires that do not result in substantial tree canopy loss at the scale of a 30 m pixel. Fires within recent forest loss due to other drivers are also excluded. Therefore, this data does not include the burning of felled logs following mechanical canopy removal, which is common in slash and burn agriculture and large-scale deforestation.
Consistent with the global tree cover loss map on GFW, this data only maps the first stand replacing forest disturbance for each pixel between 2001 and 2025. Areas of tree cover loss due to fire that occurred when forest regrowth followed an initial disturbance early in the study period are not detected in this data.
Comparing trends across the 2000-2010 and 2011-2025 periods should be [performed with caution](https://www.globalforestwatch.org/blog/data/20-years-global-tree-cover-loss-data-trends/).

## Options (pull_data)

- context layer `primary_forest`: Shows tree cover loss due to fires within humid tropical primary forests across pan-tropical regions. Default to this layer for general forest loss or deforestation requests when the AOI is within its extent, unless the user explicitly asks for all tree cover, non-primary/secondary forest, plantations, or otherwise indicates they want forest types beyond primary forest.
- context layer `intact_forest`: Tree cover loss due to fires within intact forest landscapes (IFLs) — large, undisturbed natural forest expanses free of significant human activity. Use this layer when the user explicitly asks for intact forest loss, or as the default context layer for deforestation/forest loss requests when primary_forest is not available for the AOI.
- `canopy_cover`, one of [10, 15, 20, 25, 30, 50, 75]: Minimum percent each 30m pixel is covered by forest canopy in year 2000 to count as a forest.

## Citation

Tyukavina, A., P. Potapov, M.C. Hansen, A.H. Pickens, S.V. Stehman, S. Turubanova, D. Parker, et al. 2022. “Global Trends of Forest Loss Due to Fire From 2001 to 2019.” Frontiers in Remote Sensing 3. [https://www.frontiersin.org/article/10.3389/frsen.2022.825190](https://www.frontiersin.org/journals/remote-sensing/articles/10.3389/frsen.2022.825190/). Data available at [https://glad.umd.edu/dataset/Fire_GFL/](https://glad.umd.edu/dataset/Fire_GFL/)
