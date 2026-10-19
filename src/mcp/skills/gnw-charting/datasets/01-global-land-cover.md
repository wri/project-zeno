# Global land cover (dataset 1)

Global land cover (2015-2024). Land cover and land use classes at 30 m: bare ground and sparse vegetation, short vegetation, tree cover, wetlands, water, snow/ice, cropland, cultivated grasslands, built-up land. Gives the area (ha) of each class in 2015 or 2024, and the transitions between classes from 2015 to 2024. No year-by-year series between 2015 and 2024.

Dates: 2015-01-01 to 2024-12-31.

## Columns

The columns of `rows.csv` and of `pull_data`'s rows, as the GNW analytics API returns them.

| Column | Type | Unit | Holds |
|---|---|---|---|
| `aoi_id` | string |  | The area's id at the analytics API: a GADM id without its version suffix (BRA.14 for gadm:BRA.14_1), or the source's id. |
| `aoi_type` | string |  | The kind of area: admin, protected_area, key_biodiversity_area or indigenous_land. |
| `land_cover_class` | string |  | The land cover class. |
| `area_ha` | number | ha | Area. |
| `name` | string |  | The area's name, added by GNW. |

- With `change_over_time`: adds `land_cover_class_start` (the land cover class in the first year), `land_cover_class_end` (the land cover class in the last year); drops `land_cover_class`.

## Curated charts

`curated_charts` draws these with `LandCoverChangeChartGenerator` ([generators/land_cover.py](../generators/land_cover.py)).

Land cover composition as a pie, or class-to-class transitions as a
table. Classes with no area are left out.

## How to chart it

CHART TYPES: - Land cover change → table with columns: land_cover_class_start, land_cover_class_end, area_ha - Land cover composition (snapshot) → pie chart for 2024 ONLY DATA RULES: - Drop rows where area_ha = 0 - When user asks about agriculture, farming, or agricultural land: you MUST combine
  "cropland" AND "cultivated grassland" into a single "Agriculture" category. Do NOT
  show them as separate classes unless the user explicitly asks to see them separately.
- Transitions to "short vegetation" or "bare ground" may reflect seasonality,
  not real restoration or degradation — note this in output
DO/DON'T: - This is NOT an annual timeseries — do NOT attempt year-by-year charts - Only 2 snapshots exist: 2015 and 2024 - Data does NOT capture classes that stayed the same — only transitions - For composition/snapshot questions, show 2024 data ONLY

## How to present it

Clarify that this dataset shows land cover change between 2015 and 2024 only, not annual or intra-annual changes. Warn that it does not capture classes that remained unchanged. Note that transitions to "short vegetation" or "bare" may reflect seasonal variation rather than actual degradation or restoration. This shows land cover change, not necessarily land use change or conversion.

## Cautions

This dataset represents land covers and some land uses, but when calculating areas of change, it should be noted that it shows land cover change, not necessarily land use change. It also does not represent conversion, a concept defined by the Accountability Framework initiative. Caution should be used if using this land cover change data over the full time period since it does not capture all the changes in the time series, only what the pixels were in 2015 and 2024.
Transitions between the 'bare ground & sparse vegetation' and 'short vegetation' or 'wetland short vegetation' classes can be due to precipitation patterns or minor changes in vegetation cover and are not necessarily large changes in vegetation cover or degradation.
If a user asks about tree cover loss due to another land cover type, answer with both an area of TCL due to a certain driver (TCL grouped by a specific driver) and percent of loss that was due to that driver, NOT with the land cover change areas from this product.
Land cover transitions to vegetation are not necessarily restoration. Users should exercise caution if using this data at the local scale. We encourage ground-truthing data if using this for decision-making. Data is not suitable for within year dynamics like crop cycles and flood pulses.

## Colors (use these, do not invent others)
- Tree cover (tree_cover): #246E24
- Short vegetation (short_vegetation): #B9B91E
- Wetland – short vegetation (wetland_short_vegetation): #74D6B4
- Bare and sparse vegetation (bare_and_sparse_vegetation): #FEFECC
- Water (water): #6BAED6
- Snow/ice (snow_ice): #ACD1E8
- Cropland (cropland): #fff183
- Cultivated grasslands (cultivated_grasslands): #FFCD73
- Built-up (built_up): #e8765d

## Citation

Annual 30-m maps of Global Land Cover and Land Use 2015-2024 based on [GLAD Land Cover and Land Use Change](https://www.frontiersin.org/articles/10.3389/frsen.2022.856903/full) and [Global Pasture Watch Grassland class and extent](https://www.nature.com/articles/s41597-024-04139-6). Land & Carbon Lab 2025.
Sources: Potapov, P., Hansen, M. C., Pickens, A., Hernandez-Serna, A., Tyukavina, A., Turubanova, S., Zalles, V., Li, X., Khan, A., Stolle, F., Harris, N., Song, X.-P., Baggett, A., Kommareddy, I. and Kommareddy, A. 2022. The global 2000-2020 land cover and land use change dataset derived from the Landsat archive: first results. - Frontiers in Remote Sensing. 3: 856903.
Parente, L., Sloat, L., Mesquita, V., Consoli, D., Stanimirova, R., Hengl, T., Bonannella, C., Teles, N., Wheeler, I., Hunter, M., Ehrmann, S., Ferreira, L., Mattos, A. P., Oliveira, B., Meyer, C., Şahin, M., Witjes, M., Fritz, S., Malek, Z., & Stolle, F. (2024). Annual 30-m maps of global grassland class and extent (2000-2022) based on spatiotemporal Machine Learning. Scientific Data, 11(1), 1303. [doi:10.1038/s41597-024-04139-6](https://doi.org/10.1038/s41597-024-04139-6)
