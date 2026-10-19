# SBTN Natural Lands Map (dataset 3)

SBTN Natural Lands Map (2020). Baseline map of natural and non-natural land in 2020 at 30 m. Natural classes: natural forest, mangrove, natural peat forest, wetland natural forest, natural short vegetation, natural water, bare, snow. Non-natural classes: crop, built-up, non-natural tree cover, non-natural short vegetation. Gives the area of each class in 2020. Used for no-conversion (SBTN) targets. One year only, no change over time.

Dates: 2020-01-01 to 2020-12-31.

## Columns

The columns of `rows.csv` and of `pull_data`'s rows, as the GNW analytics API returns them.

| Column | Type | Unit | Holds |
|---|---|---|---|
| `natural_lands_class` | string |  | The SBTN Natural Lands class in 2020. |
| `area_ha` | number | ha | Area. |
| `aoi_id` | string |  | The area's id at the analytics API: a GADM id without its version suffix (BRA.14 for gadm:BRA.14_1), or the source's id. |
| `aoi_type` | string |  | The kind of area: admin, protected_area, key_biodiversity_area or indigenous_land. |
| `name` | string |  | The area's name, added by GNW. |

## Curated charts

`curated_charts` draws these with `NaturalLandsChartGenerator` ([generators/natural_lands.py](../generators/natural_lands.py)).

Natural lands area by class as a pie, largest class first.

## How to chart it

CHART TYPES: - Natural vs non-natural proportions → bar chart or pie chart DATA RULES: - Natural forests = classes 2, 5, 8, 9 (natural forest + mangrove + wetland natural
  forest + natural peat forest) — combine into one "Natural forest" category when
  user asks about natural forests
- Non-natural tree cover = classes 14, 17, 18 - All areas in hectares (ha) - For natural vs non-natural queries: ALWAYS group by the is_natural column (True → label 'Natural', False → label 'Non-natural'), sum area_ha across groups. Chart data MUST have exactly two rows. DO/DON'T: - This is a SINGLE YEAR (2020) snapshot — do NOT attempt timeseries or change analysis - These data do NOT represent protection status or legality of land TEMPORAL CONSTRAINT: - If user asks about change, trends, or temporal patterns: you MUST include ALL of:
  (a) State that this dataset cannot show change — it is a single 2020 snapshot
  (b) Recommend the Global Land Cover dataset by name for change analysis
  (c) This recommendation is REQUIRED, not optional

## How to present it

Clarify this is a 2020 baseline snapshot, not a timeseries. "Natural" follows the AFi definition: land that substantially resembles what would be found without major human impacts, including managed or degraded ecosystems. Does not represent legal protection status. For change analysis, suggest the Global Land Cover dataset. When reporting natural forests, specify that it combines natural forest, mangrove, wetland natural forest, and natural peat forest.

## Cautions

"Natural" and "non-natural" definitions were adapted from the Accountability Framework initiative's definition of a natural ecosystem as "one that substantially resembles - in terms of species composition, structure, and ecological function - what would be found in a given area in the absence of major human impacts" and can include managed ecosystems as well as degraded ecosystems that are expected to regenerate either naturally or through management (AFi 2024). The SBTN Natural Lands Map operationalizes this definition by using proxies based on available data that align with AFi guidance to the extent possible. These definitions may not match all uses of the term "natural" so users should exercise caution when using this map out of the conversion-free supply chains context.
This map overestimates the extent of natural lands, and while remote sensing data, on which the map is based, can provide powerful insights, additional field work should be used for validation and to understand local dynamics. Caution should be used if calculating areas with the SBTN Natural Lands Map.
Natural forests include the following classes: natural forest, natural peat forests, wetland natural forests, and mangroves (2,5,8,9).

## Colors (use these, do not invent others)
- Natural forests (natural_forests): #246E24
- Natural peat forests (natural_peat_forests): #093D09
- Natural peat short vegetation (natural_peat_short_vegetation): #99991A
- Mangroves (mangroves): #06A285
- Wet natural forests (wet_natural_forests): #589558
- Wet natural short vegetation (wet_natural_short_vegetation): #DBDB7B
- Natural short vegetation (natural_short_vegetation): #B9B91E
- Natural water (natural_water): #6BAED6
- Bare (bare): #FEFECC
- Snow (snow): #ACD1E8
- Crop (crop): #D3D3D3
- Built (built): #D3D3D3
- Non-natural tree cover (non_natural_tree_cover): #D3D3D3
- Non-natural short vegetation (non_natural_short_vegetation): #D3D3D3
- Wet non-natural tree cover (wet_non_natural_tree_cover): #D3D3D3
- Non-natural peat tree cover (non_natural_peat_tree_cover): #D3D3D3
- Wet non-natural short vegetation (wet_non_natural_short_vegetation): #D3D3D3
- Non-natural peat short vegetation (non_natural_peat_short_vegetation): #D3D3D3
- Non-natural water (non_natural_water): #D3D3D3
- Non-natural bare (non_natural_bare): #D3D3D3
- Other (other): #D3D3D3

## Citation

Mazur, E., M. Sims, E. Goldman, M. Schneider, M.D. Pirri, C.R. Beatty, F. Stolle, M. Stevenson. 2025. "SBTN Natural Lands Map v1.1: Technical Documentation". Science Based Targets for Land Version 1 - Supplementary Material. Science Based Targets Network. [SBTN Natural Lands Map Technical Documentation](https://sciencebasedtargetsnetwork.org/wp-content/uploads/2025/02/Technical-Guidance-2025-Step3-Land-v1_1-Natural-Lands-Map.pdf)
