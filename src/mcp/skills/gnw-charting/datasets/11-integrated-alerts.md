# Integrated alerts (dataset 11)

Integrated alerts (December 2023 to present). Near-real-time alerts of vegetation disturbance, clearing and deforestation at 10 m, updated daily, from the DIST-ALERT, GLAD-L, GLAD-S2 and RADD systems. Gives disturbed area (ha) by alert date and by confidence (low, high, highest = detected by several systems). Covers all vegetation; cannot be split by land cover, ecosystem or cause.

Dates: 2023-12-01 to today.

## Columns

The columns of `rows.csv` and of `pull_data`'s rows, as the GNW analytics API returns them.

| Column | Type | Unit | Holds |
|---|---|---|---|
| `aoi_id` | string |  | The area's id at the analytics API: a GADM id without its version suffix (BRA.14 for gadm:BRA.14_1), or the source's id. |
| `alert_date` | string |  | The date of the alert, YYYY-MM-DD. |
| `alert_confidence` | string |  | The alert's confidence: low, high, or highest (detected by several systems). |
| `area_ha` | number | ha | Area. |
| `aoi_type` | string |  | The kind of area: admin, protected_area, key_biodiversity_area or indigenous_land. |
| `name` | string |  | The area's name, added by GNW. |

## Curated charts

`curated_charts` draws these with `IntegratedAlertsChartGenerator` ([generators/integrated_alerts.py](../generators/integrated_alerts.py)).

Integrated alerts: daily disturbed area over time, by confidence.

One point per day per ``alert_confidence`` (low / high / highest) — there
are no driver or land-cover intersections to break down by.

Daily, not monthly, because that is the resolution the data arrives at
and the resolution the dataset is for: these alerts update whenever any
source system does, and they are read over days and weeks. A monthly
bucket also collapses the default two-week window to one or two points,
which is not a line.

Rows are summed per (day, confidence) rather than passed through, since
the analytics API returns one row per intersecting geometry and several
can share a day. Days with no alerts are absent rather than zero — the
API reports what it detected, and a fabricated zero is a claim about a
day nobody looked at that way.

Run it on a pull's rows: `python generators/run.py 11 gnw/pulls/<result_id>/rows.csv charts.json`.

## How to chart it

GNW's rules for this dataset, written for the code that draws GNW's own charts.

CHART TYPES — generate EXACTLY ONE chart for Integrated alerts, chosen by the query; never emit both a pie and a line:
- Totals / breakdown by confidence → PIE chart, one slice per confidence tier (low, high, highest), value = total area_ha summed over the period
- Alerts over time / recent trends → LINE chart ONLY (x=alert month from alert_date, y=area_ha, one line per confidence tier); the x-axis may be aggregated to month, but render it as a line, NOT as bars
- The charts list must contain exactly one chart. If the query does not clearly ask for totals, default to the LINE over time.
- Do NOT use bar charts for Integrated alerts unless specifically asked by the user
DATA RULES:
- Result columns are: aoi_id, alert_date, alert_confidence, area_ha, aoi_type
- All areas are in hectares (ha) in the area_ha column
- ALWAYS label the unit hectares (ha) in the output: on the chart's y-axis/legend and title, and on every table column header and total that shows area — never present a bare area number without "ha"
- alert_confidence values are low, high, and highest; 'highest' means detected by two or more alert systems (it may be absent when only one system covered the area/time)
- There are NO driver or land-cover intersections — do NOT create class/driver breakdowns
- If natural_lands is active, the columns are unchanged; title charts as alerts on natural lands
DO/DON'T:
- Always interpret alerts as indicators of potential disturbance, not definitive outcomes
- Recent alerts may include false positives that have not yet raised their confidence level
- Do not use alerts for area estimates or long-term trend assessment; recommend annual tree cover loss instead

## How to present it

Describe results as integrated disturbance alerts (potential vegetation and forest disturbance), not confirmed deforestation. Always state the unit hectares (ha) with every area figure in the narrative. Always reference the confidence tiers shown and the selected time range. Include a caution that explains (a) the alert systems contributing to the integrated count — DIST-ALERT, GLAD-L, GLAD-S2 and RADD — and (b) what each confidence level means: low = detected once; high = detected multiple times by a single system (two or more for GLAD-L/GLAD-S2/RADD, four or more for DIST-ALERT); highest = detected by two or more systems, which effectively eliminates false detections. Note 'highest' may not appear when only one system covered the area and time period. Clarify if the user cares about temporary disturbance vs permanent conversion; recommend annual tree cover loss for historical changes. Coverage is global.

## Cautions

Although often called 'deforestation alerts', these detect forest or vegetation disturbances and do not distinguish human-caused from other disturbance types; within plantation forests alerts may indicate timber harvesting rather than conversion to a non-forest land use. We do not recommend using alerts for global or regional trend assessment, nor for area estimates; use annual tree cover loss for that. Recent alerts include false positives that have yet to raise their confidence level and may later be removed. The 'highest confidence' level can only be achieved where more than one alert system was operating for that region and time period. Because DIST-ALERT and GLAD-L are resampled from 30m to 10m, the count of integrated alerts is much greater than the native 30m alerts and pixels may not align exactly. Confidence levels can change retroactively as source data is updated; low-confidence alerts are not shown for DIST-ALERT on GFW.

## Options (pull_data)

- context layer `natural_lands`: Restricts alerts to natural lands from the SBTN Natural Lands Map (2020 baseline), covering all natural ecosystems (natural forests, short vegetation, wetlands, peatlands, water and bare land). "Natural" means an ecosystem resembling what would be present without major human impact, including regenerated and secondary natural ecosystems; it is broader than primary or intact forest and excludes plantations, cropland and built areas. Use this layer when the user asks about alerts on natural lands or natural ecosystems, or for supply chain, EUDR, deforestation-free or no-conversion compliance questions.

## Citation

"Global Integrated Disturbance Alerts". UMD/GLAD and WUR, accessed through Global Forest Watch on [date].
