"""Holdout cases for the jev experiments, written out from the source sheets.

holdout:  GOLD offline-eval sheet rows that are not in GOLD_CASES
          (same filters as GOLD_CASES: status is not "Not doing", the
          dataset is in the catalog and not retired or excluded).
holdout2: labeled rows of tests/evals/datasets/*.csv and data/gold.csv
          that repeat no dev or GOLD query.

The ids match results/*.jsonl. Do not edit these cases to fit a variant.
"""


def case(case_id, query, dataset, dates=(None, None)):
    return {"id": case_id, "query": query, "dataset": dataset, "dates": dates}


HOLDOUT = [
    case(
        "1-002",
        "How much of Sao Paulo was impacted disturbance alerts in the second half of 2024, considering high confidence alerts only?",
        "integrated_alerts",
        ("2024-07-01", "2024-12-31"),
    ),
    case(
        "1-004",
        "Which country had the most distrubed area in November 2025, Australia or Brazil?",
        "integrated_alerts",
        ("2025-11-01", "2025-11-30"),
    ),
    case(
        "1-012",
        "How many hectares of cultivated grasslands does Alto Rio Negro Indigenous Territory have?",
        "land_cover",
        ("2024-01-01", "2024-12-11"),
    ),
    case(
        "1-013",
        "Which had more cropland area in 2024, Nigeria or Ghana?",
        "land_cover",
        ("2024-01-01", "2024-12-11"),
    ),
    case(
        "1-015",
        "Which Welsh county had the most short vegetation in 2024?",
        "land_cover",
    ),
    case(
        "1-016",
        "In Purbalingga, Indonesia what was the largest single land cover transition from 2015 to 2024?",
        "land_cover",
        ("2015-01-01", "2024-12-31"),
    ),
    case(
        "1-017",
        "How much natural grassland is there in the Bulgan Tal key biodiversity area in 2019?",
        "grasslands",
    ),
    case(
        "1-019",
        "Which year had the most natural grassland in the Blackfeet Indian reservation in Montana USA: 2015 or 2000?",
        "grasslands",
        ("2000-01-01", "2015-12-31"),
    ),
    case(
        "1-021",
        "Which communidad of Spain (Iberian peninsula only) had the least grassland in 2022?",
        "grasslands",
        ("2022-01-01", "2022-12-31"),
    ),
    case(
        "1-022",
        "In which year between 2001 and 2022 did Bolivia have the least natural grasssland coverage?",
        "grasslands",
        ("2001-01-01", "2022-12-31"),
    ),
    case(
        "1-023",
        "Which had more natural grassland coverage in 2000: North or South Dakota?",
        "grasslands",
        ("2000-01-01", "2000-12-31"),
    ),
    case(
        "1-025",
        "True or False: Pocho in Cordoba (ARG) gained natural grasslands from 2020 to 2021",
        "grasslands",
        ("2020-01-01", "2021-12-31"),
    ),
    case(
        "1-027",
        "In the Murgia Alta WDPA in Italy, how much natural short vegetation is there?",
        "natural_lands",
    ),
    case(
        "1-030",
        "Which state has the most mangroves in Senegal: Fatick or Ziguinchor?",
        "natural_lands",
    ),
    case(
        "1-031",
        "Whats the second largest natural land class by area in Cogo, Eq. Guinea?",
        "natural_lands",
    ),
    case(
        "1-032",
        "True or false, tree cover loss has increased from 2020 to 2024 in the Upper Stung Sen catchment KBA.",
        "tcl",
    ),
    case(
        "1-034",
        "In total, how much tree cover loss was recorded in Champoton community land in Mexico, between 2001 and 2024",
        "tcl",
        ("2001-01-01", "2024-12-31"),
    ),
    case(
        "1-035",
        "Which state in belgium had the least deforestation from 2005 to 2015?",
        "tcl",
        ("2005-01-01", "2015-12-31"),
    ),
    case(
        "1-037",
        "Of the Canadian provinces+territories beginning with 'N' - which had the most deforestation in 2004?",
        "tcl",
    ),
    case(
        "1-038",
        "What was the sum total of tree cover loss in Manitoba and Alberta in 2024?",
        "tcl",
    ),
    case(
        "1-039",
        "Which location in England had the most tree cover loss from 2001 to 2024: Sheffield or Wakefield?",
        "tcl",
    ),
    case(
        "1-042",
        "What was the total carbon emissions due to deforestation in the Vale do Javari indigenous land, Brazil between 2010 and 2018?",
        "tcl",
    ),
    case(
        "1-043",
        "Which state of NZ has the highest total deforestation-related carbon emissions in NZ from 2005-2020?",
        "tcl",
        ("2005-01-01", "2020-12-31"),
    ),
    case(
        "1-045",
        "True or False: In Rep. of Congo, Bouenza generated more deforestation related carbon emissions than Cuvette in 2021",
        "tcl",
        ("2021-01-01", "2021-12-31"),
    ),
    case(
        "1-046",
        "How many tonnes of CO2 was emitted in Ihorombe, Madagascar in 2019 due to tree cover loss?",
        "tcl",
    ),
    case(
        "1-047",
        "How much tree cover was gained between 2000 and 2020 in the Rio Capim KBA?",
        "tc_gain",
        ("2000-01-01", "2020-12-31"),
    ),
    case(
        "1-050",
        "Which country gained more tree cover between 2015 and 2020: France or Germany?",
        "tc_gain",
        ("2015-01-01", "2020-12-31"),
    ),
    case(
        "1-051",
        "Which province of Galicia (ESP), gained the least tree cover between 2000-2020?",
        "tc_gain",
        ("2000-01-01", "2020-12-31"),
    ),
    case(
        "1-052",
        "Which 5-year period betwween 2000 and 2020 saw Huelva, Spain gain the most tree cover?",
        "tc_gain",
        ("2000-01-01", "2020-12-31"),
    ),
    case(
        "1-053",
        "True or False: the UK has a lower net GHG flux than the Rep. of Ireland",
        "carbon_flux",
    ),
    case(
        "1-056",
        "Which norwegian state had the most tree cover in 2010?",
        "tree_cover",
    ),
    case(
        "1-057",
        "In 2000, which state had the most tree cover between Oregon and Washington?",
        "tree_cover",
    ),
    case("1-059", "What is the global total tree cover loss in 2025?", "tcl"),
    case(
        "1-061",
        "Which state in australia lost the most forest due to settlements and infra?",
        "tcl_driver",
    ),
    case(
        "1-064",
        "What is the largest driver of deforestation in Nannup, Western Australia.",
        "tcl_driver",
    ),
    case(
        "1-069",
        "Which country in the world had the most natural grassland in 2022?",
        "grasslands",
        ("2022-01-01", "2022-12-31"),
    ),
    case(
        "1-070",
        "How much tree cover loss was there in Colombia in 2025?",
        "tcl",
        ("2025-01-01", "2025-12-31"),
    ),
    case(
        "1-071",
        "Show me trends in Tree cover loss for Brazil",
        "tcl",
        ("2001-01-01", "2025-12-31"),
    ),
    case("1-072", "What is the most recent year tree cover loss data?", "tcl"),
    case(
        "1-074",
        "Using a 10% canopy density threshold, how much tree cover was lost in Finland in 2025?",
        "tcl",
        ("2025-01-01", "2025-12-31"),
    ),
    case(
        "1-077",
        "How much deforestation in intact forests in Russia in 2025?",
        "tcl",
        ("2025-01-01", "2025-12-31"),
    ),
    case(
        "1-078",
        "List the top ten countries with the largest area of tropical primary rainforest loss in 2025",
        "tcl",
    ),
    case(
        "1-079",
        "What was the peak grassland extent in mongolia?",
        "grasslands",
    ),
    case(
        "1-087",
        "How much tree cover loss in intact forests in Russia in 2025?",
        "tcl",
    ),
    case(
        "1-091",
        "Quelle superficie forestière a été perdue au Sénégal en 2022 ?",
        "tcl",
        ("2022-01-01", "2022-12-31"),
    ),
    case(
        "1-092",
        "Qual foi a área florestal perdida em Portugal em 2022?",
        "tcl",
        ("2022-01-01", "2022-12-31"),
    ),
    case(
        "1-094",
        "2022年中国损失了多少森林面积?",
        "tcl",
        ("2022-01-01", "2022-12-31"),
    ),
    case(
        "1-097",
        "Create a dashboard for Brazil. Give me an insight on tree cover loss there, then add it to the dashboard.",
        "tcl",
    ),
    case(
        "1-098",
        "Create a dashboard for Brazil and add a map layer of the Tree Cover Loss dataset to it",
        "tcl",
    ),
    case(
        "1-100",
        "Create a dashboard for Brazil with an insight on annual deforestation trends, an explainer text block, and a satellite imagery map",
        "tcl",
    ),
    case(
        "1-101",
        "Create a dashboard for Parana Brazil with two insights on deforestation, and explainer text block, and a TCL dataset map",
        "tcl",
    ),
]

HOLDOUT2 = [
    case(
        "evals:True or false: Mount Hakusan had more area with high confidence disturbance alerts in August 2024 than September 2024",
        "True or false: Mount Hakusan had more area with high confidence disturbance alerts in August 2024 than September 2024",
        "integrated_alerts",
        ("8/1/2024", "9/30/2024"),
    ),
    case(
        "evals:How much of Virunga National Park was impacted by high confidence disturbance alerts in the second half of 2024?",
        "How much of Virunga National Park was impacted by high confidence disturbance alerts in the second half of 2024?",
        "integrated_alerts",
        ("7/1/2024", "12/31/2024"),
    ),
    case(
        "evals:What percentage of disturbances in Sara, Bolivia were high confidence during July 2025?",
        "What percentage of disturbances in Sara, Bolivia were high confidence during July 2025?",
        "integrated_alerts",
        ("7/1/2025", "7/31/2025"),
    ),
    case(
        "evals:How many hectares of short vegetation does Alto Rio Negro Indigenous Territory have?",
        "How many hectares of short vegetation does Alto Rio Negro Indigenous Territory have?",
        "land_cover",
        ("2024", None),
    ),
    case(
        "evals:True or False, the largest land cover transition between 2015 and 2024 in California was short vegetation to built-up.",
        "True or False, the largest land cover transition between 2015 and 2024 in California was short vegetation to built-up.",
        "land_cover",
    ),
    case(
        "evals:Which communidad in Spain had the least grassland in 2022?",
        "Which communidad in Spain had the least grassland in 2022?",
        "grasslands",
        ("2022", "2022"),
    ),
    case(
        "evals:Which sub region of Galicia (ESP), gained the least tree cover between 2000-2020?",
        "Which sub region of Galicia (ESP), gained the least tree cover between 2000-2020?",
        "tc_gain",
        ("2000", "2020"),
    ),
    case(
        "evals:True or False: the UK has a lower net GHG flux than the Rep. of Ireland (use the latest available data)",
        "True or False: the UK has a lower net GHG flux than the Rep. of Ireland (use the latest available data)",
        "carbon_flux",
    ),
    case(
        "evals:Using the latest available data, determine whether the Canary islands a net source or sink for deforestation related emissions.",
        "Using the latest available data, determine whether the Canary islands a net source or sink for deforestation related emissions.",
        "carbon_flux",
    ),
    case(
        "evals:Using the latest available data, what was the net greenhouse gas flux for Las Palmas, Canarias (ESP)?",
        "Using the latest available data, what was the net greenhouse gas flux for Las Palmas, Canarias (ESP)?",
        "carbon_flux",
    ),
    case(
        "evals:Which state of brazil has lost the most tree cover due to permanent agriculture. Use the latest available data.",
        "Which state of brazil has lost the most tree cover due to permanent agriculture. Use the latest available data.",
        "tcl_driver",
    ),
    case(
        "evals:Which state in australia lost the most forest due to settlements and infra? Use the latest available data.",
        "Which state in australia lost the most forest due to settlements and infra? Use the latest available data.",
        "tcl_driver",
    ),
    case(
        "evals:True or False: Logging causes more more tree cover loss than Wildfire in Aveiro, Portugal? Use the latest available data",
        "True or False: Logging causes more more tree cover loss than Wildfire in Aveiro, Portugal? Use the latest available data",
        "tcl_driver",
    ),
    case(
        "evals:What is the largest driver of deforestation in Nannup, Western Australia. Use the latest available data,",
        "What is the largest driver of deforestation in Nannup, Western Australia. Use the latest available data,",
        "tcl_driver",
    ),
    case(
        "evals:Which country in the world had the most grassland in 2022?",
        "Which country in the world had the most grassland in 2022?",
        "grasslands",
        ("1/1/2022", "12/31/2022"),
    ),
    case(
        "pzb-1270:Which of the four countries of the United Kingdom (England, Northern Ireland, Scotland, Wales) had the least natural grassland in 2022?",
        "Which of the four countries of the United Kingdom (England, Northern Ireland, Scotland, Wales) had the least natural grassland in 2022?",
        "grasslands",
    ),
    case(
        "pzb-1270:How much natural grassland was there in the USA in 2022?",
        "How much natural grassland was there in the USA in 2022?",
        "grasslands",
    ),
    case(
        "pzb-1270:Natural grassland in England in 2022",
        "Natural grassland in England in 2022",
        "grasslands",
    ),
    case("pzb-1270:Forest loss in the US", "Forest loss in the US", "tcl"),
    case(
        "pzb-1270:Which provinces in Spain lost the most forest between 2010 and 2020?",
        "Which provinces in Spain lost the most forest between 2010 and 2020?",
        "tcl",
        ("2010-01-01", "2020-12-31"),
    ),
    case(
        "pzb-1270:Compare natural grassland extent across municipalities of China in 2022",
        "Compare natural grassland extent across municipalities of China in 2022",
        "grasslands",
        ("2022-01-01", "2022-12-31"),
    ),
    case(
        "pzb-1270:Forest loss by province in Canada",
        "Forest loss by province in Canada",
        "tcl",
    ),
    case(
        "pzb-1270:Tree cover loss by borough in Kenya",
        "Tree cover loss by borough in Kenya",
        "tcl",
    ),
    case(
        "pzb-1270:Compare provinces in Spain and Canada by forest loss",
        "Compare provinces in Spain and Canada by forest loss",
        "tcl",
    ),
    case(
        "pzb-1271:Tree cover loss in Bristol, England",
        "Tree cover loss in Bristol, England",
        "tcl",
    ),
    case(
        "pzb-1271:Tree cover loss in Warwickshire, England",
        "Tree cover loss in Warwickshire, England",
        "tcl",
    ),
    case(
        "pzb-909:Which US state lost more forest due to wildfires? Washington or Oregon? Use the latest available data",
        "Which US state lost more forest due to wildfires? Washington or Oregon? Use the latest available data",
        "tcl_fires",
    ),
    case(
        "pzb-909:What is the tree cover loss in Navajo territory USA in 2024",
        "What is the tree cover loss in Navajo territory USA in 2024",
        "tcl",
    ),
    case(
        "pzb-909:show me tree cover loss in Cobaipo protected area in Bolivia",
        "show me tree cover loss in Cobaipo protected area in Bolivia",
        "tcl",
    ),
    case(
        "pzb-909:In the Kurtjar People territory in Australia - what percentage of land is non-natural?",
        "In the Kurtjar People territory in Australia - what percentage of land is non-natural?",
        "natural_lands",
    ),
    case(
        "pzb_1011_evals:Compare tree cover loss due to fires in Brazil and Indonesia from 2015 to 2024",
        "Compare tree cover loss due to fires in Brazil and Indonesia from 2015 to 2024",
        "tcl_fires",
        ("2015-01-01", "2024-12-31"),
    ),
    case(
        "pzb_1011_evals:Which had more fire-driven tree cover loss in 2023: Brazil or Indonesia?",
        "Which had more fire-driven tree cover loss in 2023: Brazil or Indonesia?",
        "tcl_fires",
        ("2023-01-01", "2023-12-31"),
    ),
    case(
        "pzb_1011_evals:Show me annual fire-driven tree cover loss in the Democratic Republic of Congo from 2001 to 2024",
        "Show me annual fire-driven tree cover loss in the Democratic Republic of Congo from 2001 to 2024",
        "tcl_fires",
        ("2001-01-01", "2024-12-31"),
    ),
    case(
        "pzb_1011_evals:How much tree cover loss was due to fires in Bolivia in 2020?",
        "How much tree cover loss was due to fires in Bolivia in 2020?",
        "tcl_fires",
        ("2020-01-01", "2020-12-31"),
    ),
    case(
        "gold:What was the sum total of tree cover loss in Manitoba in 2004 and that in Alberta in 2024?",
        "What was the sum total of tree cover loss in Manitoba in 2004 and that in Alberta in 2024?",
        "tcl",
    ),
    case(
        "gold:True or False: Logging causes more more tree cover loss than Wildfire in Aveiro, Portugal?  Use the latest available data",
        "True or False: Logging causes more more tree cover loss than Wildfire in Aveiro, Portugal?  Use the latest available data",
        "tcl_driver",
    ),
    case(
        "gold:How can I cite the Tree cover loss by dominant driver dataset in my research?",
        "How can I cite the Tree cover loss by dominant driver dataset in my research?",
        "tcl_driver",
    ),
    case(
        "gold:Which country in the world has the most grassland in 2022?",
        "Which country in the world has the most grassland in 2022?",
        "grasslands",
        ("1/1/2020", "12/31/2020"),
    ),
]
