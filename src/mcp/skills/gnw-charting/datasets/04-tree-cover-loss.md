# Tree cover loss (dataset 4)

Tree cover loss (2001-2025). Annual area (ha) of tree cover loss at 30 m for all vegetation over 5 m tall, and the annual greenhouse gas emissions from that loss (MgCO2e). Can be limited to primary forest or intact forest to measure deforestation. Supports a canopy cover threshold. Time step is one year; no monthly or seasonal values. Does not give the cause of the loss.

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
| `name` | string |  | The area's name, added by GNW. |

- With context layer `natural_forest`: `carbon_emissions_MgCO2e` can be empty.

## Curated charts

`curated_charts` draws these with `TCLChartGenerator` ([generators/tcl.py](../generators/tcl.py)).

Tree Cover Loss: annual loss area + annual GHG emissions, as two bars.

Run it on a pull's rows: `python generators/run.py 4 gnw/pulls/<result_id>/rows.csv charts.json`.

## How to chart it

GNW's rules for this dataset, written for the code that draws GNW's own charts: where they say REFUSE, decline that request and say why.

CHART TYPES: - Yearly loss → bar chart (x=year, y=area_ha) - Cumulative loss → stacked-area chart - Emissions → MUST be a SEPARATE chart from loss area (NEVER combine on same chart) DATA RULES: - Always include GHG emissions (MgCO2e) alongside loss area, but in a SEPARATE chart, except with natural_forest below a 30% threshold where emissions are null; do not chart them - Drop rows where area_ha = 0 - Use 30% canopy density threshold by default (10% with natural_forest) - If primary_forest or intact_forest variable is active, filter accordingly DO/DON'T: - If none of primary_forest, intact_forest or natural_forest is active, DO NOT use the term "deforestation"; use "tree cover loss" - If user asks for intra-year or seasonal breakdown, REFUSE — data is annual only - If user asks for net gain/loss, REFUSE — methodologies differ between loss and gain datasets - Warn about 2001-2010 vs 2011-2025 methodology difference when showing trends across both periods CHART TITLES when intact_forest is active: the metric is tree cover loss occurring INSIDE intact forest landscapes, a different measurement from the reduction of intact forest extent. Never title a chart in a way that reads as intact forest being lost — not "Intact Forest Loss", not "Intact Forests Loss", and not as a qualifier of another metric such as "Emissions from Intact Forest Loss". Name the metric "Tree Cover Loss in Intact Forests", and "Carbon Emissions from Tree Cover Loss in Intact Forests" for the emissions chart. That is the metric phrase to embed, not the whole title: still include the cadence, the area of interest and the period as you normally would, e.g. "Annual Tree Cover Loss in Intact Forests in DRC (2001-2025)"

## How to present it

Use "tree cover loss" rather than "deforestation" only when no primary, intact or natural forest context layer is applied. When intact_forest is applied, "deforestation" may describe the process but never takes intact forest as its object. This measures canopy loss only; it doesn't track regrowth or permanence. Always state the canopy density threshold used (30% by default). With natural_forest, state the threshold used (10% by default), that natural forest follows the SBTN Natural Lands Map 2020 baseline (broader than primary forest, excluding plantations), and that results cover 2021 onward; if the threshold is below 30%, explicitly state that GHG emissions are not available because the carbon model requires a canopy cover threshold of 30% or greater, and that the user can request a 30% or higher threshold to get them. Say "natural forest loss" or "tree cover loss in natural forests". If showing emissions, clarify units are MgCO2e (tonnes of CO2 equivalent). If trend spans 2001-2025, note the methodology change after 2010. If the primary_forest context layer is applied, prefer the concise "primary forest loss" over "primary forest tree cover loss". If the intact_forest context layer is applied, do NOT use "intact forest loss" or any wording that reads as intact forest being lost: this dataset measures tree cover loss occurring *inside* intact forest landscapes, which is a different quantity from the reduction in IFL extent that the IFL dataset itself publishes. Say "tree cover loss in intact forests" or "tree cover loss within intact forest landscapes". This applies to chart titles, axis labels and prose alike, and titles must use the same wording as the charts themselves — e.g. "Annual Tree Cover Loss in Intact Forests in DRC (2001-2025)", never "Annual Intact Forest Loss". It holds just as much when the phrase qualifies a different metric: carbon emissions are "emissions from tree cover loss in intact forests", never "emissions from intact forest loss". Never name intact forest as the thing being lost, whatever the verb: not "intact forest loss", not "intact forests loss", and not "deforestation of intact forest". CHART TITLES: each chart title must reflect only the metric(s) actually plotted in that chart — do not mention emissions in a title if the chart only shows area, and do not mention area if the chart only shows emissions.

## Cautions

In this data set, "tree cover" is defined as all vegetation greater than 5 meters in height, and may take the form of natural forests or plantations across a range of canopy densities. "Loss" indicates the removal or mortality of tree cover and can be due to a variety of factors, including mechanical harvesting, fire, disease, or storm damage. As such, "loss" does not equate to deforestation.
Due to variation in research methodology and date of content, tree cover, loss, and gain data sets on GFW cannot be compared accurately against each other. Accordingly, "net" loss cannot be calculated by subtracting figures for tree cover gain from tree cover loss, and current (post-2000) tree cover cannot be determined by subtracting figures for annual tree cover loss from year 2000 tree cover.
The 2011-2025 data was produced using an updated methodology: https://storage.googleapis.com/earthenginepartners-hansen/GFC-2025-v1.13/download.html. Comparisons between the original 2001-2010 data and the 2011-2025 update should be performed with caution.
In the original publication, the authors evaluated the overall prevalence of false positives (commission errors) in this data at 13%, and the prevalence of false negatives (omission errors) at 12%, though the accuracy varies by biome and thus may be higher or lower in any particular location. The model often misses disturbances in smallholder landscapes, resulting in lower accuracy of the data in sub-Saharan Africa, where this type of disturbance is more common. Largely because of a delay between an actual disturbance and the event being observed by the satellite imagery, the authors are 75% confident that the loss occurred within the stated year, and 97% confident that it occurred within a year before or after. Users of the data can smooth out such uncertainty by examining the average over multiple years. Read our blog series: globalforestwatch.org/blog/data/how-accurate-is-accurate-enough-examining-the-glad-global-tree-cover-change-data-part-1.htm; on the accuracy of this data for more information.

## Options (pull_data)

- context layer `primary_forest`: Shows tree cover loss within humid tropical primary forests across pan-tropical regions. Default to this layer for general forest loss or deforestation requests when the AOI is within its extent, unless the user explicitly asks for all tree cover, natural forest, non-primary/secondary forest, plantations, or otherwise indicates they want forest types beyond primary forest. Do not use for supply chain, EUDR or no-conversion questions; use natural_forest instead.
- context layer `intact_forest`: Tree cover loss within intact forest landscapes (IFLs) — large, undisturbed natural forest expanses free of significant human activity. Use this layer when the user explicitly asks for intact forest loss, or as the default context layer for deforestation/forest loss requests when primary_forest is not available for the AOI.
- context layer `natural_forest`: Tree cover loss within natural forests from the SBTN Natural Lands Map (2020 baseline). "Natural forest" resembles what would be present without major human impact, including regenerated and secondary natural forest; it is broader than primary or intact forest and excludes plantations. Use this layer when the user asks about natural forest, or for supply chain, EUDR, deforestation-free or no-conversion compliance questions; it takes precedence over primary_forest in those cases. Only covers loss from 2021 onward. Tree cover loss filtered by natural forest defaults to a >= 10% canopy cover threshold; only set a canopy_cover parameter if the user explicitly asks for a different threshold. GHG emissions are only available at a canopy cover threshold of 30% or greater.
- `canopy_cover`, one of [10, 15, 20, 25, 30, 50, 75]: Minimum percent each 30m pixel is covered by forest canopy in year 2000 to count as a forest.

## Colors (use these, do not invent others)
- single series: #DC6C9A

## Citation

Hansen et al., 2013. "High-Resolution Global Maps of 21st-Century Forest Cover Change." Accessed through Global Forest Watch on [date]. [www.globalforestwatch.org](https://www.globalforestwatch.org)
Learn more: https://storage.googleapis.com/earthenginepartners-hansen/GFC-2025-v1.13/download.html
