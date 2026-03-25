"""
Pre-baked analytics response data for tiered-instructions eval suite.

Each fixture builds a complete `state` dict matching what `generate_insights`
expects: state["dataset"] (from pick_dataset) + state["statistics"] (from pull_data).

The data shapes mirror real analytics API responses but are hardcoded so tests
are deterministic on the data side — only LLM calls are live.
"""

from src.agent.state import Statistics
from src.agent.tools.datasets_config import DATASETS as _ALL_DATASETS

_DS_BY_ID = {ds["dataset_id"]: ds for ds in _ALL_DATASETS}


def _dataset_fields(dataset_id: int, context_layer=None) -> dict:
    """Extract the fields generate_insights reads from state['dataset']."""
    ds = _DS_BY_ID[dataset_id]
    result = {
        "dataset_id": ds["dataset_id"],
        "dataset_name": ds["dataset_name"],
        "context_layer": context_layer,
        "tile_url": ds.get("tile_url", ""),
        "analytics_api_endpoint": ds.get("analytics_api_endpoint", ""),
        "description": ds.get("description", ""),
        "prompt_instructions": ds.get("prompt_instructions", ""),
        "methodology": ds.get("methodology", ""),
        "cautions": ds.get("cautions", ""),
        "function_usage_notes": ds.get("function_usage_notes", ""),
        "citation": ds.get("citation", ""),
    }
    # Add tiered fields when present
    for field in (
        "selection_hints",
        "code_instructions",
        "presentation_instructions",
    ):
        val = ds.get(field)
        if val:
            result[field] = val
    return result


# ---------------------------------------------------------------------------
# Dataset 4: Tree Cover Loss — annual loss + emissions for Pará, Brazil
# ---------------------------------------------------------------------------
TCL_STATE = {
    "dataset": _dataset_fields(4),
    "statistics": [
        Statistics(
            dataset_name="Tree cover loss",
            source_url="http://example.com/analytics/tcl-eval",
            start_date="2015-01-01",
            end_date="2022-12-31",
            aoi_names=["Pará, Brazil"],
            data={
                "year": [2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022],
                "area_ha": [
                    798045,
                    688012,
                    654321,
                    723456,
                    891034,
                    812345,
                    746231,
                    701234,
                ],
                "emissions_MgCO2e": [
                    354021,
                    302456,
                    289012,
                    318765,
                    395432,
                    360123,
                    331098,
                    310456,
                ],
                "aoi_id": ["BRA.14"] * 8,
                "aoi_type": ["admin"] * 8,
            },
        )
    ],
}


# ---------------------------------------------------------------------------
# Dataset 4: Tree Cover Loss — state-level comparison across the United States
# ---------------------------------------------------------------------------
_US_STATES = [
    "Alabama",
    "Alaska",
    "Arizona",
    "Arkansas",
    "California",
    "Colorado",
    "Connecticut",
    "Delaware",
    "Florida",
    "Georgia",
    "Hawaii",
    "Idaho",
    "Illinois",
    "Indiana",
    "Iowa",
    "Kansas",
    "Kentucky",
    "Louisiana",
    "Maine",
    "Maryland",
    "Massachusetts",
    "Michigan",
    "Minnesota",
    "Mississippi",
    "Missouri",
    "Montana",
    "Nebraska",
    "Nevada",
    "New Hampshire",
    "New Jersey",
    "New Mexico",
    "New York",
    "North Carolina",
    "North Dakota",
    "Ohio",
    "Oklahoma",
    "Oregon",
    "Pennsylvania",
    "Rhode Island",
    "South Carolina",
    "South Dakota",
    "Tennessee",
    "Texas",
    "Utah",
    "Vermont",
    "Virginia",
    "Washington",
    "West Virginia",
    "Wisconsin",
    "Wyoming",
]

_US_STATE_LOSS_HA = [
    8420,
    9130,
    12650,
    10440,
    28910,
    11480,
    3980,
    2210,
    24760,
    19410,
    1730,
    6820,
    5410,
    4980,
    3120,
    4660,
    7210,
    15890,
    2870,
    4150,
    3320,
    6140,
    5770,
    10980,
    7360,
    8240,
    2690,
    5880,
    2410,
    3540,
    9730,
    4210,
    16520,
    1850,
    6330,
    12110,
    14240,
    5120,
    950,
    11880,
    2130,
    13470,
    31750,
    4320,
    1210,
    8460,
    15640,
    6010,
    4470,
    1780,
]

TCL_US_STATES_STATE = {
    "dataset": _dataset_fields(4),
    "statistics": [
        Statistics(
            dataset_name="Tree cover loss",
            source_url="http://example.com/analytics/tcl-us-states-eval",
            start_date="2022-01-01",
            end_date="2022-12-31",
            aoi_names=["United States"],
            data={
                "subregion": _US_STATES,
                "value": _US_STATE_LOSS_HA,
                "year": [2022] * len(_US_STATES),
                "aoi_id": ["USA"] * len(_US_STATES),
                "aoi_type": ["admin"] * len(_US_STATES),
            },
        )
    ],
}


# ---------------------------------------------------------------------------
# Dataset 8: Tree Cover Loss by Driver — driver breakdown for Indonesia
# ---------------------------------------------------------------------------
TCL_DRIVER_STATE = {
    "dataset": _dataset_fields(8, context_layer="driver"),
    "statistics": [
        Statistics(
            dataset_name="Tree cover loss by dominant driver",
            source_url="http://example.com/analytics/tcl-driver-eval",
            start_date="2001-01-01",
            end_date="2024-12-31",
            aoi_names=["Indonesia"],
            data={
                "driver": [
                    "Permanent agriculture",
                    "Shifting cultivation",
                    "Logging",
                    "Wildfire",
                    "Hard commodities",
                    "Settlements and infrastructure",
                    "Other natural disturbances",
                    "Unknown",
                ],
                "area_ha": [
                    4523100,
                    3214500,
                    2876400,
                    1543200,
                    234500,
                    187600,
                    412300,
                    98700,
                ],
                "emissions_MgCO2e": [
                    2012340,
                    1423560,
                    1278900,
                    687450,
                    104230,
                    83400,
                    183200,
                    43800,
                ],
                "aoi_id": ["IDN"] * 8,
                "aoi_type": ["admin"] * 8,
            },
        )
    ],
}


# ---------------------------------------------------------------------------
# Dataset 0: DIST-ALERT with driver context layer — monthly alerts by driver for DRC
# ---------------------------------------------------------------------------
_dist_months = [
    "2024-06",
    "2024-07",
    "2024-08",
    "2024-09",
    "2024-10",
    "2024-11",
]
_dist_drivers = [
    "Conversion",
    "Fire-related",
    "Cropland dynamics",
    "Water-related",
    "Unclassified",
]
# Build a flat long-format table: every month × every driver
_dist_alert_dates = []
_dist_alert_drivers = []
_dist_alert_areas = []
_base_areas = {
    "Conversion": [12345, 14567, 11234, 13456, 15678, 12890],
    "Fire-related": [8901, 9234, 18765, 21034, 7654, 6543],
    "Cropland dynamics": [4567, 5123, 4890, 5234, 4678, 5012],
    "Water-related": [2345, 1987, 2456, 2123, 2678, 2234],
    "Unclassified": [3210, 3456, 3123, 3567, 3890, 3234],
}
for i, month in enumerate(_dist_months):
    for driver in _dist_drivers:
        _dist_alert_dates.append(month)
        _dist_alert_drivers.append(driver)
        _dist_alert_areas.append(float(_base_areas[driver][i]))

# ---------------------------------------------------------------------------
# Dataset 1: Global Land Cover — change transitions for Brazil
# ---------------------------------------------------------------------------
LAND_COVER_STATE = {
    "dataset": _dataset_fields(1),
    "statistics": [
        Statistics(
            dataset_name="Global land cover",
            source_url="http://example.com/analytics/land-cover-eval",
            start_date="2015-01-01",
            end_date="2024-12-31",
            aoi_names=["Brazil"],
            data={
                "land_cover_class_start": [
                    "Tree cover",
                    "Tree cover",
                    "Tree cover",
                    "Short vegetation",
                    "Short vegetation",
                    "Cropland",
                    "Cropland",
                    "Bare ground and sparse vegetation",
                ],
                "land_cover_class_end": [
                    "Cropland",
                    "Short vegetation",
                    "Built-up land",
                    "Cropland",
                    "Tree cover",
                    "Built-up land",
                    "Short vegetation",
                    "Short vegetation",
                ],
                "area_ha": [
                    1234567,
                    567890,
                    123456,
                    890123,
                    345678,
                    78901,
                    45678,
                    234567,
                ],
                "aoi_id": ["BRA"] * 8,
                "aoi_type": ["admin"] * 8,
            },
        )
    ],
}


# ---------------------------------------------------------------------------
# Dataset 2: Grasslands — annual natural/semi-natural grassland extent for Kenya
# ---------------------------------------------------------------------------
GRASSLANDS_STATE = {
    "dataset": _dataset_fields(2),
    "statistics": [
        Statistics(
            dataset_name="Global natural/semi-natural grassland extent",
            source_url="http://example.com/analytics/grasslands-eval",
            start_date="2000-01-01",
            end_date="2022-12-31",
            aoi_names=["Kenya"],
            data={
                "year": list(range(2000, 2023)),
                "area_ha": [
                    28456000,
                    28234000,
                    28012000,
                    27890000,
                    27678000,
                    27456000,
                    27234000,
                    27012000,
                    26890000,
                    26678000,
                    26456000,
                    26345000,
                    26234000,
                    26123000,
                    26012000,
                    25901000,
                    25790000,
                    25679000,
                    25568000,
                    25457000,
                    25346000,
                    25235000,
                    25124000,
                ],
                "aoi_id": ["KEN"] * 23,
                "aoi_type": ["admin"] * 23,
            },
        )
    ],
}


# ---------------------------------------------------------------------------
# Dataset 3: SBTN Natural Lands — 2020 snapshot for Colombia
# ---------------------------------------------------------------------------
NATURAL_LANDS_STATE = {
    "dataset": _dataset_fields(3),
    "statistics": [
        Statistics(
            dataset_name="SBTN Natural Lands Map",
            source_url="http://example.com/analytics/natural-lands-eval",
            start_date="2020-01-01",
            end_date="2020-12-31",
            aoi_names=["Colombia"],
            data={
                "natural_lands_class": [
                    "Natural forest",
                    "Mangrove",
                    "Natural peat forest",
                    "Wetland natural forest",
                    "Natural short vegetation",
                    "Natural water",
                    "Bare",
                    "Snow",
                    "Crop",
                    "Built-up",
                    "Non-natural tree cover",
                    "Non-natural short vegetation",
                ],
                "class_id": [2, 5, 8, 9, 3, 4, 6, 7, 14, 15, 17, 18],
                "area_ha": [
                    34567890,
                    1234567,
                    890123,
                    2345678,
                    5678901,
                    1234567,
                    345678,
                    12345,
                    8901234,
                    2345678,
                    3456789,
                    1234567,
                ],
                "aoi_id": ["COL"] * 12,
                "aoi_type": ["admin"] * 12,
            },
        )
    ],
}


# ---------------------------------------------------------------------------
# Dataset 5: Tree Cover Gain — cumulative gain for Indonesia
# ---------------------------------------------------------------------------
TREE_COVER_GAIN_STATE = {
    "dataset": _dataset_fields(5),
    "statistics": [
        Statistics(
            dataset_name="Tree cover gain",
            source_url="http://example.com/analytics/tcg-eval",
            start_date="2000-01-01",
            end_date="2020-12-31",
            aoi_names=["Indonesia"],
            data={
                "period": ["2000-2020", "2005-2020", "2010-2020", "2015-2020"],
                "area_ha": [4567890, 3456789, 2345678, 1234567],
                "aoi_id": ["IDN"] * 4,
                "aoi_type": ["admin"] * 4,
            },
        )
    ],
}


# ---------------------------------------------------------------------------
# Dataset 6: Forest GHG Net Flux — total flux for Brazil
# ---------------------------------------------------------------------------
GHG_FLUX_STATE = {
    "dataset": _dataset_fields(6),
    "statistics": [
        Statistics(
            dataset_name="Forest greenhouse gas net flux",
            source_url="http://example.com/analytics/ghg-flux-eval",
            start_date="2001-01-01",
            end_date="2024-12-31",
            aoi_names=["Brazil"],
            data={
                "flux_type": ["Gross emissions", "Gross removals", "Net flux"],
                "flux_MgCO2e": [12345678900, -8765432100, 3580246800],
                "aoi_id": ["BRA"] * 3,
                "aoi_type": ["admin"] * 3,
            },
        )
    ],
}


# ---------------------------------------------------------------------------
# Dataset 7: Tree Cover — 2000 snapshot for Democratic Republic of Congo
# ---------------------------------------------------------------------------
TREE_COVER_STATE = {
    "dataset": _dataset_fields(7),
    "statistics": [
        Statistics(
            dataset_name="Tree cover",
            source_url="http://example.com/analytics/tree-cover-eval",
            start_date="2000-01-01",
            end_date="2000-12-31",
            aoi_names=["Democratic Republic of Congo"],
            data={
                "canopy_density_bin": [
                    "0%",
                    "1-10%",
                    "11-20%",
                    "21-30%",
                    "31-40%",
                    "41-50%",
                    "51-60%",
                    "61-70%",
                    "71-80%",
                    "81-90%",
                    "91-100%",
                ],
                "area_ha": [
                    0,
                    12345678,
                    8901234,
                    6789012,
                    5678901,
                    4567890,
                    5678901,
                    7890123,
                    9012345,
                    10123456,
                    11234567,
                ],
                "aoi_id": ["COD"] * 11,
                "aoi_type": ["admin"] * 11,
            },
        )
    ],
}


# ---------------------------------------------------------------------------
# Dataset 9: sLUC Emission Factors — crop emission factors for Brazil
# ---------------------------------------------------------------------------
SLUC_EF_STATE = {
    "dataset": _dataset_fields(9),
    "statistics": [
        Statistics(
            dataset_name="Deforestation (sLUC) Emission Factors by Agricultural Crop",
            source_url="http://example.com/analytics/sluc-ef-eval",
            start_date="2024-01-01",
            end_date="2024-12-31",
            aoi_names=["Brazil"],
            data={
                "crop": [
                    "Soybean",
                    "Soybean",
                    "Soybean",
                    "Oil palm",
                    "Oil palm",
                    "Oil palm",
                    "Cattle",
                    "Cattle",
                    "Cattle",
                    "Cocoa",
                    "Cocoa",
                    "Cocoa",
                    "Coffee",
                    "Coffee",
                    "Coffee",
                ],
                "gas_type": [
                    "CO2",
                    "CH4",
                    "N2O",
                    "CO2",
                    "CH4",
                    "N2O",
                    "CO2",
                    "CH4",
                    "N2O",
                    "CO2",
                    "CH4",
                    "N2O",
                    "CO2",
                    "CH4",
                    "N2O",
                ],
                "emissions_tCO2e": [
                    4567890,
                    123456,
                    45678,
                    2345678,
                    67890,
                    23456,
                    8901234,
                    234567,
                    89012,
                    1234567,
                    34567,
                    12345,
                    567890,
                    15678,
                    5678,
                ],
                "emissions_factor_tCO2e_per_tonne_production": [
                    0.45,
                    0.012,
                    0.0045,
                    0.89,
                    0.026,
                    0.0089,
                    1.23,
                    0.034,
                    0.012,
                    2.34,
                    0.067,
                    0.023,
                    0.34,
                    0.0098,
                    0.0034,
                ],
                "production_tonnes": [
                    10150000,
                    10150000,
                    10150000,
                    2634000,
                    2634000,
                    2634000,
                    7236000,
                    7236000,
                    7236000,
                    527000,
                    527000,
                    527000,
                    1673000,
                    1673000,
                    1673000,
                ],
                "year": [2024] * 15,
                "aoi_id": ["BRA"] * 15,
                "aoi_type": ["admin"] * 15,
            },
        )
    ],
}


DIST_ALERT_STATE = {
    "dataset": _dataset_fields(0, context_layer="driver"),
    "statistics": [
        Statistics(
            dataset_name="Global all ecosystem disturbance alerts (DIST-ALERT)",
            source_url="http://example.com/analytics/dist-alert-eval",
            start_date="2024-06-01",
            end_date="2024-11-30",
            aoi_names=["Democratic Republic of Congo"],
            data={
                "alert_date": _dist_alert_dates,
                "driver": _dist_alert_drivers,
                "area_ha": _dist_alert_areas,
                "aoi_id": ["COD"] * len(_dist_alert_dates),
                "aoi_type": ["admin"] * len(_dist_alert_dates),
            },
        )
    ],
}
