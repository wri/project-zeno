from typing import Literal

DatasetNames = Literal[
    "",
    "WRI/SBTN/naturalLands/v1/2020",
    "ESA/WorldCover/v200",
    "GOOGLE/DYNAMICWORLD/V1",
    "JAXA/ALOS/PALSAR/YEARLY/FNF4",
    "JRC/GFC2020_subtypes/V0",
    "MODIS/061/MCD12Q1",
    "ESA/WorldCereal/2021/MODELS/v100",
]

layer_choices = [
    {
        "name": "SBTN Natural Lands Map v1",
        "dataset": "WRI/SBTN/naturalLands/v1/2020",
        "description": "The SBTN Natural Lands Map v1 is a 2020 baseline map of natural and non-natural land covers intended for use by companies setting science-based targets for nature, specifically the SBTN Land target #1: no conversion of natural ecosystems.  'Natural' and 'non-natural' definitions were adapted from the Accountability Framework initiative's definition of a natural ecosystem as 'one that substantially resembles - in terms of species composition, structure, and ecological function - what would be found in a given area in the absence of major human impacts' and can include managed ecosystems as well as degraded ecosystems that are expected to regenerate either naturally or through management (AFi 2024). The SBTN Natural Lands Map operationalizes this definition by using proxies based on available data that align with AFi guidance to the extent possible.  This map was made by compiling existing global and regional data.You can find the full technical note explaining the methodology linked on the Natural Lands GitHub. This work was a collaboration between Land & Carbon Lab at the World Resources Institute, World Wildlife Fund US, Systemiq, and SBTN.",
        "resolution": 30,
        "year": 2020,
        "band": "classification",
        "type": "Image",
        "class_table": {
            2: {"color": "#246E24", "name": "Natural forests"},
            3: {"color": "#B9B91E", "name": "Natural short vegetation"},
            4: {"color": "#6BAED6", "name": "Natural water"},
            5: {"color": "#06A285", "name": "Mangroves"},
            6: {"color": "#FEFECC", "name": "Bare"},
            7: {"color": "#ACD1E8", "name": "Snow"},
            8: {"color": "#589558", "name": "Wet natural forests"},
            9: {"color": "#093D09", "name": "Natural peat forests"},
            10: {"color": "#DBDB7B", "name": "Wet natural short vegetation"},
            11: {"color": "#99991A", "name": "Natural peat short vegetation"},
            12: {"color": "#D3D3D3", "name": "Crop"},
            13: {"color": "#D3D3D3", "name": "Built"},
            14: {"color": "#D3D3D3", "name": "Non-natural tree cover"},
            15: {"color": "#D3D3D3", "name": "Non-natural short vegetation"},
            16: {"color": "#D3D3D3", "name": "Non-natural water"},
            17: {"color": "#D3D3D3", "name": "Wet non-natural tree cover"},
            18: {"color": "#D3D3D3", "name": "Non-natural peat tree cover"},
            19: {
                "color": "#D3D3D3",
                "name": "Wet non-natural short vegetation",
            },
            20: {
                "color": "#D3D3D3",
                "name": "Non-natural peat short vegetation",
            },
            21: {"color": "#D3D3D3", "name": "Non-natural bare"},
        },
    },
    {
        "name": "ESA WorldCover",
        "dataset": "ESA/WorldCover/v200",
        "description": "The European Space Agency (ESA) WorldCover 10 m 2021 product provides a global land cover map for 2021 at 10 m resolution based on Sentinel-1 and Sentinel-2 data. The WorldCover product comes with 11 land cover classes and has been generated in the framework of the ESA WorldCover project, part of the 5th Earth Observation Envelope Programme (EOEP-5) of the European Space Agency.",
        "resolution": 10,
        "year": 2021,
        "band": "Map",
        "type": "ImageCollection",
        "class_table": {
            10: {"name": "Tree cover", "color": "006400"},
            20: {"name": "Shrubland", "color": "ffbb22"},
            30: {"name": "Grassland", "color": "ffff4c"},
            40: {"name": "Cropland", "color": "f096ff"},
            50: {"name": "Built-up", "color": "fa0000"},
            60: {"name": "Bare / sparse vegetation", "color": "b4b4b4"},
            70: {"name": "Snow and ice", "color": "f0f0f0"},
            80: {"name": "Permanent water bodies", "color": "0064c8"},
            90: {"name": "Herbaceous wetland", "color": "0096a0"},
            95: {"name": "Mangroves", "color": "00cf75"},
            100: {"name": "Moss and lichen", "color": "fae6a0"},
        },
    },
    {
        "name": "Dynamic World V1",
        "dataset": "GOOGLE/DYNAMICWORLD/V1",
        "description": "  Dynamic World is a 10m near-real-time (NRT) Land Use/Land Cover (LULC) dataset that includes class probabilities and label information for nine classes.  Dynamic World predictions are available for the Sentinel-2 L1C collection from 2015-06-27 to present. The revisit frequency of Sentinel-2 is between 2-5 days depending on latitude. Dynamic World predictions are generated for Sentinel-2 L1C images with CLOUDY_PIXEL_PERCENTAGE <= 35%. Predictions are masked to remove clouds and cloud shadows using a combination of S2 Cloud Probability, Cloud Displacement Index, and Directional Distance Transform. Given Dynamic World class estimations are derived from single images using a spatial context from a small moving window, top-1 'probabilities' for predicted land covers that are in-part defined by cover over time, like crops, can be comparatively low in the absence of obvious distinguishing features. High-return surfaces in arid climates, sand, sunglint, etc may also exhibit this phenomenon.  To select only pixels that confidently belong to a Dynamic World class, it is recommended to mask Dynamic World outputs by thresholding the estimated 'probability' of the top-1 prediction. ",
        "resolution": 10,
        "year": 2024,
        "band": "label",
        "type": "ImageCollection",
        "class_table": {
            0: {
                "name": "True desert 3% short vegetation cover",
                "color": "FEFECC",
            },
            1: {
                "name": "True desert 7% short vegetation cover",
                "color": "FAFAC3",
            },
            2: {
                "name": "Semi-arid 11% short vegetation cover",
                "color": "F7F7BB",
            },
            3: {
                "name": "Semi-arid 15% short vegetation cover",
                "color": "F4F4B3",
            },
            4: {
                "name": "Semi-arid 19% short vegetation cover",
                "color": "F1F1AB",
            },
            5: {
                "name": "Semi-arid 23% short vegetation cover",
                "color": "EDEDA2",
            },
            6: {
                "name": "Semi-arid 27% short vegetation cover",
                "color": "EAEA9A",
            },
            7: {
                "name": "Semi-arid 31% short vegetation cover",
                "color": "E7E792",
            },
            8: {
                "name": "Semi-arid 35% short vegetation cover",
                "color": "E4E48A",
            },
            9: {
                "name": "Semi-arid 39% short vegetation cover",
                "color": "E0E081",
            },
            10: {
                "name": "Semi-arid 43% short vegetation cover",
                "color": "DDDD79",
            },
            11: {
                "name": "Semi-arid 47% short vegetation cover",
                "color": "DADA71",
            },
            12: {
                "name": "Semi-arid 51% short vegetation cover",
                "color": "D7D769",
            },
            13: {
                "name": "Semi-arid 55% short vegetation cover",
                "color": "D3D360",
            },
            14: {
                "name": "Semi-arid 59% short vegetation cover",
                "color": "D0D058",
            },
            15: {
                "name": "Semi-arid 63% short vegetation cover",
                "color": "CDCD50",
            },
            16: {
                "name": "Semi-arid 67% short vegetation cover",
                "color": "CACA48",
            },
            17: {
                "name": "Semi-arid 71% short vegetation cover",
                "color": "C6C63F",
            },
            18: {
                "name": "Semi-arid 75% short vegetation cover",
                "color": "C3C337",
            },
            19: {
                "name": "Dense short vegetation 79% short vegetation cover",
                "color": "C0C02F",
            },
            20: {
                "name": "Dense short vegetation 83% short vegetation cover",
                "color": "BDBD27",
            },
            21: {
                "name": "Dense short vegetation 87% short vegetation cover",
                "color": "B9B91E",
            },
            22: {
                "name": "Dense short vegetation 91% short vegetation cover",
                "color": "B6B616",
            },
            23: {
                "name": "Dense short vegetation 95% short vegetation cover",
                "color": "B3B30E",
            },
            24: {
                "name": "Dense short vegetation 100% short vegetation cover",
                "color": "B0B006",
            },
            25: {"name": "Stable tree cover 3m trees", "color": "609C60"},
            26: {"name": "Stable tree cover 4m trees", "color": "5C985C"},
            27: {"name": "Stable tree cover 5m trees", "color": "589558"},
            28: {"name": "Stable tree cover 6m trees", "color": "549254"},
            29: {"name": "Stable tree cover 7m trees", "color": "5.08E+52"},
            30: {"name": "Stable tree cover 8m trees", "color": "4C8B4C"},
            31: {"name": "Stable tree cover 9m trees", "color": "488848"},
            32: {"name": "Stable tree cover 10m trees", "color": "448544"},
            33: {"name": "Stable tree cover 11m trees", "color": "408140"},
            34: {"name": "Stable tree cover 12m trees", "color": "3C7E3C"},
            35: {"name": "Stable tree cover 13m trees", "color": "387B38"},
            36: {"name": "Stable tree cover 14m trees", "color": "347834"},
            37: {"name": "Stable tree cover 15m trees", "color": "317431"},
            38: {"name": "Stable tree cover 16m trees", "color": "2D712D"},
            39: {"name": "Stable tree cover 17m trees", "color": "2.96E+31"},
            40: {"name": "Stable tree cover 18m trees", "color": "256B25"},
            41: {"name": "Stable tree cover 19m trees", "color": "216721"},
            42: {"name": "Stable tree cover 20m trees", "color": "1D641D"},
            43: {"name": "Stable tree cover 21m trees", "color": "196119"},
            44: {"name": "Stable tree cover 22m trees", "color": "1.55E+17"},
            45: {"name": "Stable tree cover 23m trees", "color": "115A11"},
            46: {"name": "Stable tree cover 24m trees", "color": "0D570D"},
            47: {"name": "Stable tree cover 25m trees", "color": "95409"},
            48: {"name": "Stable tree cover >25m trees", "color": "65106"},
            49: {
                "name": "Tree cover with previous disturbance (2020 height) 3m trees",
                "color": "643700",
            },
            50: {
                "name": "Tree cover with previous disturbance (2020 height) 4m trees",
                "color": "643a00",
            },
            51: {
                "name": "Tree cover with previous disturbance (2020 height) 5m trees",
                "color": "643d00",
            },
            52: {
                "name": "Tree cover with previous disturbance (2020 height) 6m trees",
                "color": "644000",
            },
            53: {
                "name": "Tree cover with previous disturbance (2020 height) 7m trees",
                "color": "644300",
            },
            54: {
                "name": "Tree cover with previous disturbance (2020 height) 8m trees",
                "color": "644600",
            },
            55: {
                "name": "Tree cover with previous disturbance (2020 height) 9m trees",
                "color": "644900",
            },
            56: {
                "name": "Tree cover with previous disturbance (2020 height) 10m trees",
                "color": "654c00",
            },
            57: {
                "name": "Tree cover with previous disturbance (2020 height) 11m trees",
                "color": "654f00",
            },
            58: {
                "name": "Tree cover with previous disturbance (2020 height) 12m trees",
                "color": "655200",
            },
            59: {
                "name": "Tree cover with previous disturbance (2020 height) 13m trees",
                "color": "655500",
            },
            60: {
                "name": "Tree cover with previous disturbance (2020 height) 14m trees",
                "color": "655800",
            },
            61: {
                "name": "Tree cover with previous disturbance (2020 height) 15m trees",
                "color": "655a00",
            },
            62: {
                "name": "Tree cover with previous disturbance (2020 height) 16m trees",
                "color": "655d00",
            },
            63: {
                "name": "Tree cover with previous disturbance (2020 height) 17m trees",
                "color": "656000",
            },
            64: {
                "name": "Tree cover with previous disturbance (2020 height) 18m trees",
                "color": "656300",
            },
            65: {
                "name": "Tree cover with previous disturbance (2020 height) 19m trees",
                "color": "666600",
            },
            66: {
                "name": "Tree cover with previous disturbance (2020 height) 20m trees",
                "color": "666900",
            },
            67: {
                "name": "Tree cover with previous disturbance (2020 height) 21m trees",
                "color": "666c00",
            },
            68: {
                "name": "Tree cover with previous disturbance (2020 height) 22m trees",
                "color": "666f00",
            },
            69: {
                "name": "Tree cover with previous disturbance (2020 height) 23m trees",
                "color": "667200",
            },
            70: {
                "name": "Tree cover with previous disturbance (2020 height) 24m trees",
                "color": "667500",
            },
            71: {
                "name": "Tree cover with previous disturbance (2020 height) 25m trees",
                "color": "667800",
            },
            72: {
                "name": "Tree cover with previous disturbance (2020 height) >25m trees",
                "color": "667b00",
            },
            73: {
                "name": "Tree height gain (2020 height) 3m trees",
                "color": "ff99ff",
            },
            74: {
                "name": "Tree height gain (2020 height) 4m trees",
                "color": "FC92FC",
            },
            75: {
                "name": "Tree height gain (2020 height) 5m trees",
                "color": "F98BF9",
            },
            76: {
                "name": "Tree height gain (2020 height) 6m trees",
                "color": "F685F6",
            },
            77: {
                "name": "Tree height gain (2020 height) 7m trees",
                "color": "F37EF3",
            },
            78: {
                "name": "Tree height gain (2020 height) 8m trees",
                "color": "F077F0",
            },
            79: {
                "name": "Tree height gain (2020 height) 9m trees",
                "color": "ED71ED",
            },
            80: {
                "name": "Tree height gain (2020 height) 10m trees",
                "color": "EA6AEA",
            },
            81: {
                "name": "Tree height gain (2020 height) 11m trees",
                "color": "E763E7",
            },
            82: {
                "name": "Tree height gain (2020 height) 12m trees",
                "color": "E45DE4",
            },
            83: {
                "name": "Tree height gain (2020 height) 13m trees",
                "color": "E156E1",
            },
            84: {
                "name": "Tree height gain (2020 height) 14m trees",
                "color": "DE4FDE",
            },
            85: {
                "name": "Tree height gain (2020 height) 15m trees",
                "color": "DB49DB",
            },
            86: {
                "name": "Tree height gain (2020 height) 16m trees",
                "color": "D842D8",
            },
            87: {
                "name": "Tree height gain (2020 height) 17m trees",
                "color": "D53BD5",
            },
            88: {
                "name": "Tree height gain (2020 height) 18m trees",
                "color": "D235D2",
            },
            89: {
                "name": "Tree height gain (2020 height) 19m trees",
                "color": "CF2ECF",
            },
            90: {
                "name": "Tree height gain (2020 height) 20m trees",
                "color": "CC27CC",
            },
            91: {
                "name": "Tree height gain (2020 height) 21m trees",
                "color": "C921C9",
            },
            92: {
                "name": "Tree height gain (2020 height) 22m trees",
                "color": "C61AC6",
            },
            93: {
                "name": "Tree height gain (2020 height) 23m trees",
                "color": "C313C3",
            },
            94: {
                "name": "Tree height gain (2020 height) 24m trees",
                "color": "C00DC0",
            },
            95: {
                "name": "Tree height gain (2020 height) 25m trees",
                "color": "BD06BD",
            },
            96: {
                "name": "Tree height gain (2020 height) >25m trees",
                "color": "bb00bb",
            },
        },
    },
    {
        "name": "Global 4-class PALSAR-2/PALSAR Forest/Non-Forest Map",
        "dataset": "JAXA/ALOS/PALSAR/YEARLY/FNF4",
        "description": "The global forest/non-forest map (FNF) is generated by classifying the SAR image (backscattering coefficient) in the global 25m resolution PALSAR-2/PALSAR SAR mosaic so that strong and low backscatter pixels are assigned as 'forest' and 'non-forest', respectively. Here, 'forest' is defined as the natural forest with the area larger than 0.5 ha and forest cover over 10%. This definition is the same as the Food and Agriculture Organization (FAO) definition. Since the radar backscatter from the forest depends on the region (climate zone), the classification of Forest/Non-Forest is conducted by using a region-dependent threshold of backscatter. The classification accuracy is checked by using in-situ photos and high-resolution optical satellite images.",
        "resolution": 25,
        "year": 2018,
        "band": "fnf",
        "type": "ImageCollection",
        "class_table": {
            1: {"name": "Dense forest", "color": "00b200"},
            2: {"name": "Non-dense Forest", "color": "83ef62"},
            3: {"name": "Non-Forest", "color": "ffff99"},
            4: {"name": "Water", "color": "0000ff"},
        },
    },
    {
        "name": "Global map of forest types 2020",
        "dataset": "JRC/GFC2020_subtypes/V0",
        "description": "The global map of forest types provides a spatially explicit representation of primary forest, naturally regenerating forest and planted forest (including plantation forest) for the year 2020 at 10m spatial resolution. The base layer for mapping these forest types is the extent of forest cover of version 1 of the Global Forest Cover map for year 2020 (JRC GFC 2020). The definitions of the forest types follow the definitions of the Regulation from the European Union 'on the making available on the Union market and the export from the Union of certain commodities and products associated with deforestation and forest degradation' (EUDR, Regulation (EU) 2023/1115), which are similar to characteristics and specific forest categories from the FAO Global Forest Resources Assessment. The year 2020 corresponds to the cut-off date of the EUDR.",
        "resolution": 10,
        "year": 2020,
        "band": "GFT",
        "type": "ImageCollection",
    },
    {
        "name": "MCD12Q1.061 MODIS Land Cover Type Yearly Global 500m",
        "dataset": "MODIS/061/MCD12Q1",
        "description": "The Terra and Aqua combined Moderate Resolution Imaging Spectroradiometer (MODIS) Land Cover Type (MCD12Q1) Version 6.1 data product provides global land cover types at yearly intervals. The MCD12Q1 Version 6.1 data product is derived using supervised classifications of MODIS Terra and Aqua reflectance data. Land cover types are derived from the International Geosphere-Biosphere Programme (IGBP), University of Maryland (UMD), Leaf Area Index (LAI), BIOME-Biogeochemical Cycles (BGC), and Plant Functional Types (PFT) classification schemes. The supervised classifications then underwent additional post-processing that incorporate prior knowledge and ancillary information to further refine specific classes. Additional land cover property assessment layers are provided by the Food and Agriculture Organization (FAO) Land Cover Classification System (LCCS) for land cover, land use, and surface hydrology.",
        "resolution": 500,
        "year": 2023,
        "band": "LC_Type1",
        "type": "ImageCollection",
    },
    {
        "name": "ESA WorldCereal 10 m v100",
        "dataset": "ESA/WorldCereal/2021/MODELS/v100",
        "description": "The European Space Agency (ESA) WorldCereal 10 m 2021 product suite consists of global-scale annual and seasonal crop maps and their related confidence. They were generated as part of the ESA-WorldCereal project. More information on the content of these products and the methodology used to generate them is described in [1].  This collection contains up to 106 agro-ecological zone (AEZ) images for each product which were all processed with respect to their own regional seasonality and should be considered as independent products. These seasons are described in the list below and were developed in [2] as part of the project. Note that cereals as described by WorldCereal include wheat, barley, and rye, which belong to the Triticeae tribe.  WorldCereal seasons description:      tc-annual: a one-year cycle being defined in an AEZ by the end of the last considered growing season     tc-wintercereals: the main cereals season defined in an AEZ     tc-springcereals: optional springcereals season, only defined in certain AEZ     tc-maize-main: the main maize season defined in an AEZ     tc-maize-second: optional second maize season, only defined in certain AEZ ",
        "resolution": 10,
        "year": 2021,
        "band": "classification",
        "type": "ImageCollection",
    },
]
