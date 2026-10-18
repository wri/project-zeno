# Global natural/semi-natural grassland extent (dataset 2)

Natural/semi-natural grassland extent (2000-2022). Annual 30 m maps of natural and semi-natural grassland, which includes native grasslands, shrublands, savannas, steppes and tundra (low vegetation under 3 m). Gives grassland area (ha) for each year from 2000 to 2022 and its gain or loss between years. Does not include cultivated grassland or cropland.

Dates: 2000-01-01 to 2022-12-31.

## Curated charts

`curated_charts` draws these with `GrasslandsChartGenerator` ([generators/grasslands.py](../generators/grasslands.py)).

Grassland extent per year as a bar chart.

## How to chart it

CHART TYPES: - Area over time → bar chart or line chart (x=year, y=area_ha) - Comparison across ≤8 geographic units → pie chart - Comparison across ≥9 geographic units → table DATA RULES: - Exclude rows where area_ha = 0 or missing - All areas in hectares (ha) DO/DON'T: - Gain does NOT equal restoration — may be land abandonment, invasive species,
  woody encroachment, or temporary regrowth
- Loss does NOT equal permanent conversion — may be natural dynamics, seasonal
  variability, or floodplain inundation
- Do NOT use this for cultivated grasslands or croplands

## How to present it

Clarify that "natural/semi-natural grassland" includes grasslands, shrublands, and savannas — any low vegetation (<3m) with at least 30% cover. MUST include this caveat when discussing grassland gains: "Gains do not necessarily represent ecological restoration — they may reflect land abandonment, invasive species expansion, woody encroachment, or temporary regrowth." Losses should not be described as "permanent conversion" without qualification. For cultivated grasslands or croplands, direct users to the Global Land Cover dataset.

## Cautions

Despite the flexibility provided by the probability maps, we note several classification issues and limitation in our natural/semi-natural grassland predictions (see Table 6). Most of these issues (e.g. specially the miss-classification errors) are not trivial to resolve in the face of Random Forest as a complex and non-linear prediction system, as we are not sure these outcomes happen because of (1) extrapolation problems, (2) noise/limited detectability in the Landsat images, (3) fuzzy definition of grassland classes, (4) need of more specialized and regional/local ML models, or (5) simply a lack of training points in these areas. It appears that intensively managed grasslands, with high homogeneity under many conditions, have a high chance of being confused with other classes that have very similar spectral properties, such as urban mosaics (i.e. buildings, sparse trees and grass fields with different densities) or (greenish) croplands with similar vegetation height and spatial configuration (such as cereal crops). Less intensively cultivated grasslands, where more diverse plant species can be found and where the landscape may not be very regular, are easily confused with grasslands that are not cultivated or (semi) natural herbaceous vegetation, in general. In addition, the spectral signal of cultivated grasslands can not be as clearly distinguished from natural/semi-natural grassland as it could be from croplands, where there are clear breaks in vegetation growth in cases where multi-temporal clear-sky images are available. The distinction between cultivated and natural/semi-natural grasslands has been notoriously difficult to map in the past, which has also affected our reference data collection and harmonization process. Hence, our reference labeling protocol relied on more indirect indicators of management, such as fences and other typical infrastructure, hay bales, machine presence, and even animal presence in the field or geometric shapes of the landscape. This may lead to an underestimation of signs of cultivation that may be less intensive or where VHR imagery was not available at the time of management practices. Under-estimation of grassland extent
  Grassland extent is under-predicted in southeastern Africa (mainly in Zimbabwe and Mozambique)
  and in eastern Australia (mainly in the shrublands and woodlands of the Mulga ecoregion).
Cropland misclassified as grassland
  In the state of Montana, USA, cropland areas located on historical prairie areas have high
  probability values for natural/semi-natural grassland and low values for cultivated grassland.
  Sudan, Niger, Uganda, Kenya, and Mali have several cropland areas with high probability
  values for natural/semi-natural grassland.
Mixed farmland mosaics misclassified as grassland
  Farmland mosaics in North-Eastern Uganda's present high probability for both grassland classes,
Macroscopic errors
  Although important for grassland separation, the 1-km accessibility maps and MODIS products
  (MOD11A2 and MCD19A2) introduced curvilinear macroscopic errors (due to the downscaling
  strategy based on cubicspline) in Uruguay, Southwest Argentina, South of Angola and in
  Sahel region in Africa.
  Due to the Landsat 7 Scan Line Corrector failure, regular stripes of grassland probabilities
  are visible at parcel-level. This issue is more prominent in 2012, where GLAD Landsat ARD-2
  relies only in Landsat 7 imagery.
Spectral overlap between natural and cultivated grasslands (especially fallow fields or lightly grazed areas) can result in misclassification. Regional differences in management practices may not be detectable in global models. Data likely reflects a snapshot per year, not intra-annual dynamics or land use rotations (e.g. grazing/fallow cycles). Definitions of "natural", "semi-natural", and "cultivated" vary by region and culture; users should not assume the dataset reflects legal or ecological classifications in every context. Short-term disturbances (fire, grazing, flood) might be:
  1. Misclassified as change
  2. Undetected if recovery is rapid
  3. Dataset may not represent functional health of grasslands (e.g. degradation, productivity loss).
It's important to understand that while natural / semi-natural grassland areas can and do support grazing by wild ruminants and domestic livestock, these areas can still retain significant ecological value. These ecosystems continue to provide carbon storage, biodiversity habitat, and ecosystem services such as water regulation, pollination, and soil stabilization. However, once lost to cropland or pasture (through intensive management actions such as plowing or planting), or built areas (e.g. cities or energy infrastructure), or are seriously degraded (e.g. become bare ground) many of those benefits are lost or severely diminished. Very long crop rotations or shifting cultivation systems may be captured in our analysis as loss events. While these land use changes may be temporary or part of cyclical agricultural practices, they can resemble permanent conversion in satellite-based land cover datasets, particularly when vegetation structure changes significantly or persists across multiple years. Many forms of degradation, such as declines in plant diversity, aboveground productivity, soil health, or subtle structural changes, may not result in a detectable land cover change and are therefore not reflected as Natural / semi-natural grassland loss. Not all gross gains detected in natural / semi-natural grassland areas reflect deliberate or ecologically desirable restoration. Some observed transitions may result from land abandonment rather than active restoration, and in some cases regrowth may be dominated by invasive species or woody plant encroachment. Further, long fallow periods within rotational or shifting agricultural systems may be misclassified as gains when in fact they are part of a temporary cycle.  Some gains may reflect early successful stages or temporary states rather than mature, functioning, and recovered ecosystems. Area estimates for this analysis were derived using pixel counting, which involves summing the number of 30-m pixels classified as natural/semi-natural grasslands and converting this count to an area estimate. However, pixel counting is not best practice for area estimation., as it does not account for classification uncertainties or biases.

## Colors (use these, do not invent others)
- single series: #ff9916

## Citation

Parente, L., Sloat, L., Mesquita, V., Consoli, D., Stanimirova, R., Hengl, T., Bonannella, C., Teles, N., Wheeler, I., Hunter, M., Ehrmann, S., Ferreira, L., Mattos, A. P., Oliveira, B., Meyer, C., Şahin, M., Witjes, M., Fritz, S., Malek, Z., & Stolle, F. (2024). Annual 30-m maps of global grassland class and extent (2000-2022) based on spatiotemporal Machine Learning. Scientific Data, 11(1), 1303. [doi:10.1038/s41597-024-04139-6](https://doi.org/10.1038/s41597-024-04139-6)
