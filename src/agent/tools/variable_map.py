# Maps user-facing variable names to FAO FRA API table and variable identifiers.
# Table names correspond to the tableNames[] enum in the FAO FRA API Swagger spec.
# See: https://fra-data.fao.org/api-docs/swagger.json

VARIABLE_MAP: dict[str, dict] = {
    # --- Forest Extent ---
    "forest_area": {
        "table": "extentOfForest",
        "variables": ["forestArea", "naturallyRegeneratingForest", "plantedForest", "primaryForest"],
        "unit": "1000 ha",
        "description": "Total forest area by category (naturally regenerating, planted, primary)",
    },
    "forest_area_change": {
        "table": "forestAreaChange",
        "variables": [],
        "unit": "1000 ha/year",
        "description": "Annual net forest area change by period (deforestation minus expansion)",
    },
    "forest_area_protected": {
        "table": "forestAreaWithinProtectedAreas",
        "variables": [],
        "unit": "1000 ha",
        "description": "Forest area within nationally designated protected areas",
    },
    "permanent_forest_estate": {
        "table": "areaOfPermanentForestEstate",
        "variables": [],
        "unit": "1000 ha",
        "description": "Area designated as permanent forest estate (legally protected from conversion)",
    },
    # --- Forest Characteristics ---
    "forest_characteristics": {
        "table": "forestCharacteristics",
        "variables": [],
        "unit": "1000 ha",
        "description": "Forest composition breakdown including mangroves, bamboo, rubber plantations, and other specific forest categories",
    },
    # --- Growing Stock ---
    "growing_stock": {
        "table": "growingStockTotal",
        "variables": ["total"],
        "unit": "million m3",
        "description": "Total growing stock volume",
    },
    "growing_stock_per_ha": {
        "table": "growingStockAvg",
        "variables": [],
        "unit": "m3/ha",
        "description": "Average growing stock volume per hectare",
    },
    "growing_stock_composition": {
        "table": "growingStockComposition2025",
        "variables": [],
        "unit": "million m3",
        "description": "Growing stock by species/genus composition",
    },
    # --- Biomass ---
    "biomass": {
        "table": "biomassStockTotal",
        "variables": ["total"],
        "unit": "megatonnes",
        "description": "Total biomass stock (aboveground, belowground, deadwood combined)",
    },
    "biomass_per_ha": {
        "table": "biomassStockAvg",
        "variables": [],
        "unit": "tonnes/ha",
        "description": "Average biomass stock per hectare",
    },
    # --- Carbon Stock ---
    "carbon_stock": {
        "table": "carbonStockTotal",
        "variables": ["total"],
        "unit": "megatonnes CO2e",
        "description": "Total carbon stock across all five pools (aboveground biomass, belowground biomass, dead wood, litter, soil organic matter)",
    },
    "carbon_stock_by_pool": {
        "table": "carbonStockTotal",
        "variables": [],
        "unit": "megatonnes CO2e",
        "description": "Carbon stock broken down by all five pools",
    },
    "carbon_stock_soil_depth": {
        "table": "carbonStockSoilDepth",
        "variables": [],
        "unit": "megatonnes CO2e",
        "description": "Soil organic carbon stock by depth layer",
    },
    # --- Designated Management & Ownership ---
    "management_objectives": {
        "table": "primaryDesignatedManagementObjective",
        "variables": [],
        "unit": "1000 ha",
        "description": "Forest area by primary designated management objective (production, multiple use, conservation, protection, social services)",
    },
    "designated_management": {
        "table": "totalAreaWithDesignatedManagementObjective",
        "variables": [],
        "unit": "1000 ha",
        "description": "Total forest area with a formally designated management objective",
    },
    "management_rights": {
        "table": "holderOfManagementRights",
        "variables": [],
        "unit": "1000 ha",
        "description": "Forest area by holder of management rights to public forests (government, private, communities, indigenous peoples)",
    },
    "ownership": {
        "table": "forestOwnership",
        "variables": [],
        "unit": "1000 ha",
        "description": "Forest area by ownership category (public, private, community/indigenous, other)",
    },
    # --- Disturbances ---
    "disturbances": {
        "table": "disturbances",
        "variables": [],
        "unit": "1000 ha",
        "description": "Forest area affected by insects, disease, and severe weather events (2002–2020)",
    },
    "fire": {
        "table": "areaAffectedByFire",
        "variables": [],
        "unit": "1000 ha",
        "description": "Forest area affected by fire (2007–2019)",
    },
    "degraded_forest": {
        "table": "degradedForest2025",
        "variables": [],
        "unit": "1000 ha",
        "description": "Area of degraded forest (based on national definitions, 2025 cycle)",
    },
    # --- Restoration ---
    "forest_restoration": {
        "table": "forestRestoration",
        "variables": [],
        "unit": "1000 ha",
        "description": "Forest area under restoration or reforestation activities",
    },
}

# Sorted list of valid variable names for use in error messages and docstrings.
VALID_VARIABLES = sorted(VARIABLE_MAP.keys())
