# Tree cover gain (dataset 5)

Tree cover gain (2000-2020). Area (ha) where new tree cover over 5 m tall grew, cumulative over 2000-2020, 2005-2020, 2010-2020 and 2015-2020, at 30 m. Includes natural regrowth, forest recovery and plantation cycles. No annual values.

Dates: 2000-01-01 to 2020-12-31.

## Columns

The columns of `rows.csv` and of `pull_data`'s rows, as the GNW analytics API returns them.

| Column | Type | Unit | Holds |
|---|---|---|---|
| `aoi_id` | string |  | The area's id at the analytics API: a GADM id without its version suffix (BRA.14 for gadm:BRA.14_1), or the source's id. |
| `aoi_type` | string |  | The kind of area: admin, protected_area, key_biodiversity_area or indigenous_land. |
| `tree_cover_gain_period` | string |  | The period the gain is cumulative over, e.g. 2000-2020. |
| `area_ha` | number | ha | Area. |
| `name` | string |  | The area's name, added by GNW. |

## Curated charts

`curated_charts` draws these with `TreeCoverGainChartGenerator` ([generators/tree_cover_gain.py](../generators/tree_cover_gain.py)).

Tree cover gain per reporting period as a bar chart.

Run it on a pull's rows: `python generators/run.py 5 gnw/pulls/<result_id>/rows.csv charts.json`.

## How to chart it

GNW's rules for this dataset, written for the code that draws GNW's own charts: where they say REFUSE, decline that request and say why; "the insight" is your answer.

CHART TYPES: - Default: bar chart with one bar per CUMULATIVE period (2000-2020, 2005-2020, 2010-2020, 2015-2020) - X-axis labels MUST use the raw cumulative period labels, NOT decomposed intervals - Do NOT split cumulative periods into 5-year buckets unless the user explicitly asks DATA RULES: - Cumulative gain over 4 periods: 2000-2020, 2005-2020, 2010-2020, 2015-2020 - ONLY if user explicitly asks for a specific sub-period (e.g., "gain between 2005 and 2010"):
  calculate Area[Y1 to Y2] = Area[Y1 to 2020] - Area[Y2 to 2020]
- All areas in hectares (ha) DO/DON'T: - Do NOT use the term "restoration" — use "tree cover gain" - If user asks for net gain/loss or net change: EITHER refuse entirely OR show gain
  data with a MANDATORY warning. Either way, the insight text MUST state that gain and
  loss datasets use different methodologies and CANNOT be combined for net change.
- These are estimates suitable as indicators, NOT for precise verification of
  restoration activities at local scales

## How to present it

Use "tree cover gain" not "restoration" — gain includes plantation cycles, natural regrowth, and land abandonment, not just ecological restoration. Tree cover gain is defined as vegetation growing from under 5m to over 5m height. Cannot be subtracted from tree cover loss for net change — different methodologies. ALWAYS include this warning when net change is discussed: "Tree cover gain and tree cover loss use fundamentally different methodologies, time periods, and definitions. They cannot be subtracted to calculate net change." Note these are estimates suitable as indicators, not for local-scale verification.

## Cautions

In this data set, "tree cover" is defined as woody vegetation with the height of 5 m and taller, and may take the form of natural woodlands, forests, or tree plantations across a range of canopy densities. Tree cover gain does not equate directly to restoration, afforestation or reforestation. Integrated use of other products such as canopy cover density data also available on GFW should be performed with caution. The authors evaluated the accuracy of the product, and the overall accuracy was found to be 99.3%, commission error (false positives) of 28.6%, and omission error (false negatives) of 42.2%. The accuracy does vary by biome and thus may be higher or lower in any particular location. As the omission error is higher than the commission error, this indicates that the product provides conservative estimates of forest dynamics. There was confusion between forest enhancement (existing forest height increase) and forest gain (establishment of forests within the year 2000 non-forest land), and this was more prominent in boreal forest areas where forest height in the year 2000 was difficult to determine.

## Colors (use these, do not invent others)
- single series: #3F08F5

## Citation

Use the following credit when this data is displayed: Accessed through Global Forest Watch on <date>. [www.globalforestwatch.org](https://www.globalforestwatch.org). Use the following credit when this data is cited: Potapov, P., Hansen, M.C., Pickens, A., Hernandez-Serna, A., Tyukavina, A., Turubanova, S., Zalles, V., Li, X., Khan, A., Stolle, F., Harris, N., Song, X-P., Baggett, A., Kommareddy, I., and Kommareddy, A. 2022. The Global 2000-2020 Land Cover and Land Use Change Dataset Derived From the Landsat Archive: First Results. Frontiers in Remote Sensing, 13, April 2022. [doi:10.3389/frsen.2022.856903](https://doi.org/10.3389/frsen.2022.856903)
