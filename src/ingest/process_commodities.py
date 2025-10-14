import geopandas as gpd

CODE_TO_COMMODITY = {
    "BANA": "Banana",
    "BARL": "Barley",
    "BEAN": "Bean",
    "CASS": "Cassava",
    "CHIC": "Chickpea",
    "CNUT": "Coconut",
    "COCO": "Cocoa",
    "ACOF": "Arabica_Coffee",
    "RCOF": "Robusta_Coffee",
    "COTT": "Cotton",
    "COWP": "Cowpea",
    "GROU": "Groundnut",
    "LENT": "Lentil",
    "MAIZ": "Maize",
    "PMIL": "Pearl_Millet",
    "SMIL": "Small_Millet",
    "OILP": "Oil_Palm",
    "PIGE": "Pigeon_Pea",
    "PLNT": "Plantain",
    "POTA": "Potato",
    "RAPE": "Rapeseed",
    "RICE": "Rice",
    "SESA": "Sesame_Seed",
    "SORG": "Sorghum",
    "SOYB": "Soybean",
    "SUGB": "Sugarbeet",
    "SUGC": "Sugarcane",
    "SUNF": "Sunflower",
    "SWPO": "Sweet_Potato",
    "TEAS": "Tea",
    "TOBA": "Tobacco",
    "WHEA": "Wheat",
    "YAMS": "Yams",
}

# Drop geometry
tab = gpd.read_file("data/all_commodities_adm2_ch4.gpkg")
tab = tab.drop(columns="geometry")

# Melt and save to parquet
index = ["GID_0", "GID_1", "GID_2", "NAME_0", "NAME_1", "NAME_2"]

tab = tab.set_index(index).melt(ignore_index=False)

tab = tab.dropna()

split = tab.variable.str.split("_", expand=True)

year = split[0].str.split("EF", expand=True)[1]

commodity = split[1].map(CODE_TO_COMMODITY)

tab = tab.assign(year=year, commodity=commodity)
tab = tab.reset_index()
tab = tab.drop(columns="variable")

tab.to_parquet("data/all_commodities_adm2_ch4_nogeom.parquet")
