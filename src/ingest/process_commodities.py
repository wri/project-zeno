import pandas as pd

CODE_TO_COMMODITY = {
    "BANA": "Banana",
    "BARL": "Barley",
    "BEAN": "Bean",
    "CASS": "Cassava",
    "CHIC": "Chickpea",
    "CNUT": "Coconut",
    "COCO": "Cocoa",
    "ACOF": "Arabica Coffee",
    "RCOF": "Robusta Coffee",
    "COTT": "Cotton",
    "COWP": "Cowpea",
    "GROU": "Groundnut",
    "LENT": "Lentil",
    "MAIZ": "Maize",
    "PMIL": "Pearl Millet",
    "SMIL": "Small Millet",
    "OILP": "Oil Palm",
    "PIGE": "Pigeon Pea",
    "PLNT": "Plantain",
    "POTA": "Potato",
    "RAPE": "Rapeseed",
    "RICE": "Rice",
    "SESA": "Sesame Seed",
    "SORG": "Sorghum",
    "SOYB": "Soybean",
    "SUGB": "Sugarbeet",
    "SUGC": "Sugarcane",
    "SUNF": "Sunflower",
    "SWPO": "Sweet Potato",
    "TEAS": "Tea",
    "TOBA": "Tobacco",
    "WHEA": "Wheat",
    "YAMS": "Yams",
}

# Drop geometry
for admin_level in range(3):
    print(f"Admin level {admin_level}")

    tab = pd.read_csv(
        f"data/emission_factors_CO2e_ADM{admin_level}_master.csv"
    )
    print(tab.head())

    # Melt and save to parquet
    for i in range(admin_level):
        print(f"Dropping column {i}")
        tab = tab.drop(columns=f"GID_{i}")

    index = [f"GID_{admin_level}", "crop_type"]

    tab = tab.set_index(index).melt(ignore_index=False)

    print(f"Count before dropping {tab.shape}")
    tab = tab.dropna(how="all")
    print(f"Count after dropping {tab.shape}")

    split = tab.variable.str.split("_", expand=True)

    year = split[1].astype("uint16")

    variable = split[0]

    tab = tab.drop(columns="variable")
    tab = tab.assign(year=year, variable=variable)
    tab = tab.reset_index()

    cols = [col for col in tab.columns if col != "value"] + ["value"]
    tab = tab[cols]

    tab["crop_type"] = tab.crop_type.map(CODE_TO_COMMODITY)

    tab.to_parquet(
        f"data/emission_factors_CO2e_ADM{admin_level}_master.parquet"
    )


# aws s3 cp data/emission_factors_CO2e_ADM0_master.parquet s3://zeno-static-data/emission_factors_CO2e_ADM0_master.parquet
# aws s3 cp data/emission_factors_CO2e_ADM1_master.parquet s3://zeno-static-data/emission_factors_CO2e_ADM1_master.parquet
# aws s3 cp data/emission_factors_CO2e_ADM2_master.parquet s3://zeno-static-data/emission_factors_CO2e_ADM2_master.parquet
