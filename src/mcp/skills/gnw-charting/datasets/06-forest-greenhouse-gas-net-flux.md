# Forest greenhouse gas net flux (dataset 6)

Forest greenhouse gas net flux (2001-2025). Forest carbon balance at 30 m: greenhouse gas emissions from forest disturbance, carbon removals by forest growth, and the net flux between them (MgCO2e). Negative net flux means a carbon sink, positive means a source. One value for the whole 2001-2025 period (total or annual average); no year-by-year values.

Dates: 2001-01-01 to 2025-12-31.

## Columns

The columns of `rows.csv` and of `pull_data`'s rows, as the GNW analytics API returns them.

| Column | Type | Unit | Holds |
|---|---|---|---|
| `aoi_id` | string |  | The area's id at the analytics API: a GADM id without its version suffix (BRA.14 for gadm:BRA.14_1), or the source's id. |
| `aoi_type` | string |  | The kind of area: admin, protected_area, key_biodiversity_area or indigenous_land. |
| `carbon_net_flux_Mg_CO2e` | number | MgCO2e | Net flux: emissions minus removals. Negative is a sink, positive a source. One value for the dataset's whole period. |
| `carbon_gross_emissions_Mg_CO2e` | number | MgCO2e | Gross emissions from forest disturbance, over the dataset's period. |
| `carbon_gross_removals_Mg_CO2e` | number | MgCO2e | Gross removals by forest growth, over the dataset's period. |
| `name` | string |  | The area's name, added by GNW. |

## Curated charts

`curated_charts` draws these with `ForestFluxChartGenerator` ([generators/forest_flux.py](../generators/forest_flux.py)).

Gross emissions, gross removals and net flux as a diverging bar
chart, with removals drawn below the axis.

## How to chart it

CHART TYPES: - Net flux → split/diverging bar chart (emissions positive y-axis, removals negative) DATA RULES: - Values are TOTALS over model period 2001-2025 — present them as totals, NOT annual values - Do NOT divide by 25 in code — keep the raw period totals - Do NOT pre-calculate or present annual averages - 30% canopy density threshold (fixed, cannot be changed) - Units: MgCO2e (tonnes of CO2 equivalent) DO/DON'T: - DO NOT show trends over time or annual values — this is a single-period aggregate - DO NOT attempt timeseries charts - Use "net sink" for net-negative flux (removals > emissions) - Use "net source" for net-positive flux (emissions > removals)

## How to present it

Clarify that values represent total flux over 2001-2025, not annual figures. Mention that users can divide by 25 to estimate an annual average, but DO NOT perform this division — always present the raw totals as primary values. Use "net sink" for negative values, "net source" for positive values. Note the 30% canopy density threshold is fixed. This is a modeled product with inherent uncertainty — higher in removals than emissions.

## Cautions

Data are the product of modeling and thus have an inherent degree of error and uncertainty. Users are strongly encouraged to read and fully comprehend the metadata and other availabledocumentation prior to data use. Net flux reflects the total over the model period of 2001-2025, not an annual time series from which a trend can be derived. Thus, values must be divided by 25 to calculate average annual net flux. Uncertainty is higher in gross removals than emissions, particularly driven by uncertainty in removal factors. These uncertainties are propagated to the uncertainty in net flux. Values are applicable to forest areas only (canopy cover >30 percent and >5 m height or areas with tree cover gain). See Harris et al. (2021) for further information on the forest definition used in the analysis. Emissions reflect stand-replacing disturbances as observed in Landsat satellite imagery and do not include emissions from unobserved forest degradation. Activity data used as the basis of the estimates contain temporal inconsistencies: Removals data contain temporal inconsistencies because tree cover gain represents a cumulative total from 2000-2020, rather than annual gains as estimated through 2025. Improvements in the detection of tree cover loss due to the incorporation of new satellite data and methodology changes between 2011 and 2015 may result in higher estimates of emissions in recent years compared to earlier years. Refer here for additional information. Large jumps in net flux along some boundary are due to the use of ecozone-specific removal factors. The changes in net flux occur at ecozone boundaries, where different removal factors are applied on each side. This dataset has been updated since its original publication. See Overview for more information.

## Options (pull_data)

- `canopy_cover`, one of [30, 50, 75]: Minimum percent each 30m pixel is covered by forest canopy in year 2000 to count as a forest.

## Colors (use these, do not invent others)
- positive / negative: positive #9a65c0, negative #137375

## Citation

Harris et al. (2021). Global maps of 21st century forest carbon fluxes. Accessed on <date> from Global Forest Watch.
