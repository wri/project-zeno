# Deforestation (sLUC) Emission Factors by Agricultural Crop (dataset 9)



Dates: 2020-01-01 to 2024-12-31.

## Columns

The columns of `rows.csv` and of `pull_data`'s rows, as the GNW analytics API returns them.

| Column | Type | Unit | Holds |
|---|---|---|---|
| `aoi_id` | string |  | The area's id at the analytics API: a GADM id without its version suffix (BRA.14 for gadm:BRA.14_1), or the source's id. |
| `aoi_type` | string |  | The kind of area: admin, protected_area, key_biodiversity_area or indigenous_land. |
| `crop_type` | string |  | The agricultural crop. |
| `gas_type` | string |  | The greenhouse gas. |
| `year` | integer |  | The year the value is for. |
| `emissions_factor_tCO2e_per_tonne_production` | number | tCO2e/t | Emissions from land use change per tonne of the crop produced. |
| `emissions_tCO2e` | number | tCO2e | Emissions from land use change. |
| `production_tonnes` | number | t | Crop production. |
| `name` | string |  | The area's name, added by GNW. |

## Curated charts

`curated_charts` draws these with `SlucEmissionFactorsChartGenerator` ([generators/sluc.py](../generators/sluc.py)).

Emissions by gas type as a pie, plus emissions by crop as a table.

## How to chart it

CHART TYPES:
- Proportional emissions by gas type (CO2, CH4, N2O) → pie chart (single crop)
- Multiple crops in one location, or one crop across locations → table
- Summary of EF + emissions → table
DATA RULES:
- Actual column names in data: crop, gas_type, emissions_tco2e, emission_factor_tco2e_per_tonne
- For pie chart: group by gas_type, sum emissions_tco2e. Use name=gas_type, value=emissions_tco2e in chart data.
- For table (multiple crops): group by crop, sum emissions_tco2e and sum emission_factor_tco2e_per_tonne. Save ALL rows to chart_data.csv.
- Always include units in output: tCO2e for emissions
DO/DON'T:
- DO NOT combine EF + total emissions on the same bar chart
- If user asks for a map or spatial visualization: REFUSE — this dataset is tabular only
- Always clarify the reporting year (2020-2024)

## How to present it

Always include units: tCO2e for emissions, tonnes for production volume. Note: tCO2e = MgCO2e (metric tonnes of CO2 equivalent). Clarify the reporting year (default 2024). Note that emission factors quantify emissions from deforestation linked to agricultural expansion, not all land use emissions. Not all crops are available for all regions. This is tabular data only — no map visualization is possible.

## Cautions

Users should be aware of several limitations when utilizing the sLUC emission factors: - Data Resolution: The underlying geospatial datasets vary in resolution, which may affect
  accuracy at finer spatial scales, particularly for small administrative units (ADM2).
- Crop Coverage: Not all 42 crops are available for every region due to data constraints,
  potentially limiting comprehensive assessments in certain areas.
- Temporal Alignment: While the assessment period is 2001-2020, emission factors are reported
  for 2020-2024, which may introduce discrepancies if land use dynamics have shifted significantly.
- Methodological Assumptions: The linear discounting approach assumes a uniform decay of emissions
  relevance over time, which may not capture complex land use change dynamics.
Users are encouraged to review the full methodology and associated publications to understand these limitations and ensure appropriate application of the data in their specific contexts.

## Citation

Fitts, L.A., O. James, D. Gibbs, E. Goldman, N. Harris, M. Ramlow, L. Sloat, B. Wielgosz, C. Wilson, C. Winchester, A. Ernstoff, T. Hohmann, V. Rossi, A. Stern. 2025. Statistical land use change emissions from deforestation and land occupation for 42 agricultural crop categories. WRI Technical Note. [url pending]
