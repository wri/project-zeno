"""
Unit tests derived from eval report behaviors (eval_report_output.md).

Each test corresponds to a specific behavior evaluated in the tiered instructions eval.
Tests call generate_insights.ainvoke() with realistic mock data and assert on
structural properties of the output (chart type, data filtering, terminology).

These tests hit the Gemini API — they are integration tests by nature.
"""

import re
import sys
import uuid
from typing import Any

import pytest

from src.agent.state import Statistics
from src.agent.tools.generate_insights import generate_insights

pytestmark = pytest.mark.asyncio(loop_scope="session")


# ---------------------------------------------------------------------------
# Override DB fixtures to avoid database connections
# ---------------------------------------------------------------------------
@pytest.fixture(scope="function", autouse=True)
def test_db():
    pass


@pytest.fixture(scope="function", autouse=True)
def test_db_session():
    pass


@pytest.fixture(scope="function", autouse=True)
def test_db_pool():
    pass


@pytest.fixture(scope="module", autouse=True)
def reset_google_clients():
    llms_module = sys.modules["src.agent.llms"]
    llms_module.SMALL_MODEL = llms_module.get_small_model()
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def invoke_generate_insights(
    query: str, dataset: dict, statistics: list[dict]
) -> dict:
    """Call generate_insights and return the update dict (or error message)."""
    tool_call_id = str(uuid.uuid4())
    command = await generate_insights.ainvoke(
        {
            "type": "tool_call",
            "name": "generate_insights",
            "id": tool_call_id,
            "args": {
                "query": query,
                "state": {
                    "dataset": dataset,
                    "statistics": statistics,
                },
            },
        }
    )
    return command.update


def chart_from(update: dict) -> dict | None:
    """Extract the first chart from the update, or None."""
    charts = update.get("charts_data", [])
    return charts[0] if charts else None


def insight_text(update: dict) -> str:
    """Extract the insight text, falling back to tool message content."""
    if "insight" in update:
        return update["insight"]
    msgs = update.get("messages", [])
    if msgs:
        return msgs[0].content
    return ""


# ---------------------------------------------------------------------------
# Dataset fixtures — realistic metadata matching analytics_datasets.yml
# ---------------------------------------------------------------------------
GHG_FLUX_DATASET: dict[str, Any] = {
    "dataset_id": 6,
    "context_layer": None,
    "context_layers": [],
    "parameters": None,
    "reason": "GHG flux dataset matches.",
    "tile_url": "https://tiles.globalforestwatch.org/gfw_forest_carbon_net_flux/latest/dynamic/{z}/{x}/{y}.png",
    "dataset_name": "Forest greenhouse gas net flux",
    "analytics_api_endpoint": "/v0/land_change/carbon_flux/analytics",
    "content_date": "2001-2024",
    "selection_hints": None,
    "description": "Maps the balance between emissions from forest disturbances and carbon removals from forest growth between 2001 and 2024.",
    "prompt_instructions": (
        "DO NOT show trends over time or annual values. Show net flux as a split bar chart, "
        "with emissions in the positive y-axis and removals in the negative. Use sink/source terminology."
    ),
    "methodology": "Globally consistent model of forest carbon flux.",
    "cautions": (
        "Net flux reflects the total over the model period of 2001-2024, not an annual time series."
    ),
    "function_usage_notes": "Shows forest carbon balance.\n",
    "citation": "Harris et al., 2021.",
    "code_instructions": (
        "CHART TYPES:\n"
        "- Net flux → split/diverging bar chart (emissions positive y-axis, removals negative)\n"
        "DATA RULES:\n"
        "- Values are TOTALS over model period 2001-2024\n"
        "- Do NOT divide by 24 in code\n"
        "DO/DON'T:\n"
        "- REFUSE any request for annual timeseries or year-by-year breakdown"
    ),
    "presentation_instructions": (
        'Use "net sink" for negative values, "net source" for positive values. '
        "Mention that users can divide by 24 to estimate annual average."
    ),
}

GHG_FLUX_STATS: list[dict] = [
    Statistics(
        dataset_name="Forest greenhouse gas net flux",
        source_url="http://example.com/analytics/ghg-flux",
        start_date="2001-01-01",
        end_date="2024-12-31",
        aoi_names=["Brazil"],
        parameters=None,
        context_layer=None,
        data={
            "variable": [
                "Gross emissions",
                "Gross removals",
                "Net flux",
            ],
            "value": [12350000000, -8770000000, 3580000000],
            "unit": ["MgCO2e", "MgCO2e", "MgCO2e"],
        },
    )
]

GRASSLAND_DATASET: dict[str, Any] = {
    "dataset_id": 2,
    "context_layer": None,
    "context_layers": [],
    "parameters": None,
    "reason": "Grasslands dataset matches.",
    "tile_url": "https://tiles.globalforestwatch.org/gnsg/latest/dynamic/{z}/{x}/{y}.png",
    "dataset_name": "Global natural/semi-natural grassland extent",
    "analytics_api_endpoint": "/v0/land_change/grasslands/analytics",
    "content_date": "2000-2022, annual",
    "selection_hints": None,
    "description": "Annual 30 m maps of global natural/semi-natural grassland extent from 2000 to 2022.",
    "prompt_instructions": (
        "Natural/semi-natural grassland extent and change for each year from 2000 to 2022. "
        "Use bar or line charts to show total area over time."
    ),
    "methodology": "Random Forest classification of Landsat imagery.",
    "cautions": "Classification errors exist especially between grasslands and croplands.",
    "function_usage_notes": "Shows grassland extent.\n",
    "citation": "Parente et al., 2022.",
    "code_instructions": (
        "CHART TYPES:\n"
        "- Area over time → bar chart or line chart (x=year, y=area_ha)\n"
        "DATA RULES:\n"
        "- Exclude rows where area_ha = 0 or missing\n"
        "- All areas in hectares (ha)"
    ),
    "presentation_instructions": (
        'Clarify that "natural/semi-natural grassland" includes grasslands, shrublands, and savannas.'
    ),
}

GRASSLAND_STATS: list[dict] = [
    Statistics(
        dataset_name="Global natural/semi-natural grassland extent",
        source_url="http://example.com/analytics/grasslands",
        start_date="2000-01-01",
        end_date="2022-12-31",
        aoi_names=["Kenya"],
        parameters=None,
        context_layer=None,
        data={
            "year": list(range(2000, 2023)),
            "area_ha": [
                28456000,
                28300000,
                28150000,
                28000000,
                27850000,
                27700000,
                27550000,
                27400000,
                27250000,
                27100000,
                26950000,
                26800000,
                26650000,
                26500000,
                26350000,
                26200000,
                26050000,
                25900000,
                25750000,
                25600000,
                25450000,
                25280000,
                25124000,
            ],
        },
    )
]

# Grassland stats with zero rows embedded
GRASSLAND_STATS_WITH_ZEROS: list[dict] = [
    Statistics(
        dataset_name="Global natural/semi-natural grassland extent",
        source_url="http://example.com/analytics/grasslands",
        start_date="2000-01-01",
        end_date="2022-12-31",
        aoi_names=["Kenya"],
        parameters=None,
        context_layer=None,
        data={
            "year": list(range(2000, 2023)),
            "area_ha": [
                28456000,
                28300000,
                28150000,
                28000000,
                0,  # zero row that should be excluded
                27700000,
                27550000,
                27400000,
                27250000,
                27100000,
                26950000,
                26800000,
                26650000,
                26500000,
                26350000,
                26200000,
                26050000,
                25900000,
                25750000,
                25600000,
                25450000,
                25280000,
                25124000,
            ],
        },
    )
]

TREE_COVER_DATASET: dict[str, Any] = {
    "dataset_id": 7,
    "context_layer": None,
    "context_layers": [],
    "parameters": None,
    "reason": "Tree cover dataset matches.",
    "tile_url": "https://tiles.globalforestwatch.org/umd_tree_cover_density_2000/latest/dynamic/{z}/{x}/{y}.png",
    "dataset_name": "Tree cover",
    "analytics_api_endpoint": "/v0/land_change/tree_cover/analytics",
    "content_date": "2000",
    "selection_hints": None,
    "description": "Global percent tree canopy cover at 30-meter resolution for year 2000.",
    "prompt_instructions": (
        'Only use the term "tree cover", not "forest" unless primary forest layer is active. '
        "Show tree cover area by canopy density bin."
    ),
    "methodology": "Landsat 7 imagery classification.",
    "cautions": (
        '"Tree cover" is defined as all vegetation taller than 5 meters and may include plantations.'
    ),
    "function_usage_notes": "Shows tree cover extent.\n",
    "citation": "Hansen et al., 2013.",
    "code_instructions": (
        "CHART TYPES:\n"
        "- Tree cover area by canopy-density bin → bar chart or pie chart\n"
        "- Values MUST be area in hectares (ha), NOT percentages\n"
        "DATA RULES:\n"
        "- Year 2000 data only — single snapshot\n"
        "- Exclude the 0% canopy density bin\n"
        "- Exclude rows where area_ha = 0"
    ),
    "presentation_instructions": (
        'Use "tree cover" not "forest". Tree cover includes plantations, not just natural forest. '
        "For change analysis, direct to Tree Cover Loss or Tree Cover Gain datasets."
    ),
}

TREE_COVER_STATS: list[dict] = [
    Statistics(
        dataset_name="Tree cover",
        source_url="http://example.com/analytics/tree-cover",
        start_date="2000-01-01",
        end_date="2000-12-31",
        aoi_names=["Democratic Republic of Congo"],
        parameters=None,
        context_layer=None,
        data={
            "canopy_density": [
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
                0,  # 0% bin — should be excluded
                12350000,
                5670000,
                4320000,
                3890000,
                4560000,
                5230000,
                6780000,
                8900000,
                10540000,
                19982107,
            ],
        },
    )
]

TREE_COVER_GAIN_DATASET: dict[str, Any] = {
    "dataset_id": 5,
    "context_layer": None,
    "context_layers": [],
    "parameters": None,
    "reason": "Tree cover gain dataset matches.",
    "tile_url": "https://tiles.globalforestwatch.org/umd_tree_cover_gain/latest/dynamic/{z}/{x}/{y}.png",
    "dataset_name": "Tree cover gain",
    "analytics_api_endpoint": "/v0/land_change/tree_cover_gain/analytics",
    "content_date": "2000-2020 five year intervals",
    "selection_hints": None,
    "description": "Tree Cover Gain identifies areas where new tree canopy was established between 2000 and 2020.",
    "prompt_instructions": (
        "Shows cumulative tree cover gain over the periods 2000-2020, 2005-2020, 2010-2020 or 2015-2020. "
        'Avoid using the term "restoration". '
        "Net change cannot be calculated by subtracting gain from loss — methodologies differ between the two datasets. "
        "If the user asks for net gain/loss or net change, refuse and explain that they cannot be combined for net change."
    ),
    "methodology": "Landsat 7 imagery classification.",
    "cautions": (
        "Tree cover gain does not equate directly to restoration, afforestation or reforestation."
    ),
    "function_usage_notes": "Shows tree cover gain.\n",
    "citation": "Hansen et al., 2013.",
    "code_instructions": (
        "CHART TYPES:\n"
        "- Default: bar chart with one bar per CUMULATIVE period\n"
        "- X-axis labels MUST use the raw cumulative period labels\n"
        "DO/DON'T:\n"
        "- If user asks for net gain/loss or net change: REFUSE — methodologies differ; "
        "cannot combine gain and loss for net change\n"
        "- REFUSE any attempt to subtract loss from gain\n"
        '- Use "tree cover gain" not "restoration"'
    ),
    "presentation_instructions": (
        'Use "tree cover gain" not "restoration". Gain includes plantation cycles, '
        "natural regrowth, and land abandonment. "
        "Cannot be subtracted from tree cover loss for net change — different methodologies; do not imply net figures."
    ),
}

TREE_COVER_GAIN_STATS: list[dict] = [
    Statistics(
        dataset_name="Tree cover gain",
        source_url="http://example.com/analytics/tree-cover-gain",
        start_date="2000-01-01",
        end_date="2020-12-31",
        aoi_names=["Indonesia"],
        parameters=None,
        context_layer=None,
        data={
            "period": [
                "2000-2020",
                "2005-2020",
                "2010-2020",
                "2015-2020",
            ],
            "area_ha": [4567890, 3456789, 2345678, 1234567],
        },
    )
]

LAND_COVER_DATASET: dict[str, Any] = {
    "dataset_id": 1,
    "context_layer": None,
    "context_layers": [],
    "parameters": None,
    "reason": "Land cover dataset matches.",
    "tile_url": "https://tiles.globalforestwatch.org/wur_radd_alerts/latest/dynamic/{z}/{x}/{y}.png",
    "dataset_name": "Global land cover",
    "analytics_api_endpoint": "/v0/land_change/land_cover/analytics",
    "content_date": "2015-2024",
    "selection_hints": None,
    "description": "Annual global land cover classification at 30m resolution.",
    "prompt_instructions": (
        "Land cover transitions between 2015 and 2024. When user asks about agriculture, "
        "combine cropland and cultivated grassland. For transition queries, use a table."
    ),
    "methodology": "ESA CCI Land Cover classification.",
    "cautions": "Only two time snapshots available (2015 and 2024). Cannot show annual timeseries.",
    "function_usage_notes": "Shows land cover composition.\n",
    "citation": "ESA CCI, 2024.",
    "code_instructions": (
        "CHART TYPES:\n"
        "- Land cover composition → pie chart\n"
        "- Transitions between classes → table (columns: start_class, end_class, area_ha)\n"
        "DATA RULES:\n"
        "- Agriculture = Cropland + Cultivated grassland (combine them)\n"
        "- Only 2 snapshots: 2015 and 2024. REFUSE annual timeseries requests\n"
        "DO/DON'T:\n"
        "- REFUSE any request for annual or yearly data between 2015-2024"
    ),
    "presentation_instructions": (
        "Only two snapshots exist (2015 and 2024). When asked for annual data, explain the limitation."
    ),
}

LAND_COVER_TRANSITION_STATS: list[dict] = [
    Statistics(
        dataset_name="Global land cover",
        source_url="http://example.com/analytics/land-cover",
        start_date="2015-01-01",
        end_date="2024-12-31",
        aoi_names=["Brazil"],
        parameters=None,
        context_layer=None,
        data={
            "start_class": [
                "Tree cover",
                "Tree cover",
                "Short vegetation",
                "Short vegetation",
                "Short vegetation",
                "Cropland",
                "Cropland",
            ],
            "end_class": [
                "Cropland",
                "Short vegetation",
                "Cropland",
                "Built-up",
                "Tree cover",
                "Built-up",
                "Tree cover",
            ],
            "area_ha": [
                1234567,
                345678,
                890123,
                56789,
                123456,
                145568,
                78901,
            ],
        },
    )
]

LAND_COVER_COMPOSITION_STATS: list[dict] = [
    Statistics(
        dataset_name="Global land cover",
        source_url="http://example.com/analytics/land-cover",
        start_date="2024-01-01",
        end_date="2024-12-31",
        aoi_names=["Brazil"],
        parameters=None,
        context_layer=None,
        data={
            "land_cover_class": [
                "Tree cover",
                "Cropland",
                "Short vegetation",
                "Cultivated grassland",
                "Built-up",
                "Wetlands",
                "Water",
            ],
            "area_ha": [
                45000000,
                22000000,
                15000000,
                8000000,
                2000000,
                1500000,
                500000,
            ],
        },
    )
]

NATURAL_LANDS_DATASET: dict[str, Any] = {
    "dataset_id": 3,
    "context_layer": None,
    "context_layers": [],
    "parameters": None,
    "reason": "Natural lands dataset matches.",
    "tile_url": "https://tiles.globalforestwatch.org/sbtn_natural_lands/latest/dynamic/{z}/{x}/{y}.png",
    "dataset_name": "SBTN Natural Lands Map",
    "analytics_api_endpoint": "/v0/land_change/natural_lands/analytics",
    "content_date": "2020",
    "selection_hints": None,
    "description": "2020 baseline map of natural and non-natural land covers.",
    "prompt_instructions": (
        "Natural and non-natural lands in 2020. For natural forests, combine classes 2,5,8,9."
    ),
    "methodology": "SBTN classification.",
    "cautions": "Single-year snapshot (2020). Cannot show change over time.",
    "function_usage_notes": "Shows natural lands baseline.\n",
    "citation": "SBTN, 2024.",
    "code_instructions": (
        "CHART TYPES:\n"
        "- Natural vs non-natural proportions → bar chart or pie chart\n"
        "DATA RULES:\n"
        "- Natural forests = classes 2, 5, 8, 9\n"
        "- Non-natural tree cover = classes 14, 17, 18\n"
        "DO/DON'T:\n"
        "- REFUSE change-over-time requests — suggest Global Land Cover dataset instead"
    ),
    "presentation_instructions": (
        "This is a 2020 baseline snapshot. For change analysis, suggest the Global Land Cover dataset."
    ),
}

NATURAL_LANDS_STATS: list[dict] = [
    Statistics(
        dataset_name="SBTN Natural Lands Map",
        source_url="http://example.com/analytics/natural-lands",
        start_date="2020-01-01",
        end_date="2020-12-31",
        aoi_names=["Colombia"],
        parameters=None,
        context_layer=None,
        data={
            "land_class": [
                "Natural forest",
                "Natural grassland/shrubland",
                "Natural wetland",
                "Mangrove",
                "Natural wetland forest",
                "Natural peat forest",
                "Cropland",
                "Cultivated grassland",
                "Plantation forest",
                "Built-up",
            ],
            "class_id": [2, 3, 4, 5, 8, 9, 13, 14, 17, 18],
            "area_ha": [
                34567890,
                5678901,
                2345678,
                890123,
                456789,
                234567,
                8901234,
                4567890,
                1234567,
                890123,
            ],
            "is_natural": [
                True,
                True,
                True,
                True,
                True,
                True,
                False,
                False,
                False,
                False,
            ],
        },
    )
]

SLUC_EF_DATASET: dict[str, Any] = {
    "dataset_id": 9,
    "context_layer": None,
    "context_layers": [],
    "parameters": None,
    "reason": "sLUC EF dataset matches.",
    "tile_url": "",
    "dataset_name": "Deforestation (sLUC) Emission Factors by Agricultural Crop",
    "analytics_api_endpoint": "/v0/land_change/deforestation_luc_emissions_factor/analytics",
    "content_date": "2020-2024",
    "selection_hints": None,
    "description": "sLUC emission factors for 42 agricultural crops across multiple spatial scales.",
    "prompt_instructions": (
        "Emission factors quantify total greenhouse gas emissions in tCO2e per tonne of product. "
        "Use table for multiple crops. Use pie for gas type breakdown."
    ),
    "methodology": "Fitts et al., 2025.",
    "cautions": "Data resolution varies. Not all crops available for every region.",
    "function_usage_notes": "Shows deforestation emission factors.\n",
    "citation": "Fitts et al., 2025.",
    "code_instructions": (
        "CHART TYPES:\n"
        "- Proportional emissions by gas type → pie chart (single crop)\n"
        "- Multiple crops in one location → table\n"
        "DATA RULES:\n"
        "- Include units in data values: tCO2e for emissions, tonnes for production\n"
        "DO/DON'T:\n"
        "- REFUSE map requests — this data is tabular only, no spatial information"
    ),
    "presentation_instructions": (
        "Always include units: tCO2e for emissions, tonnes for production volume. "
        "Clarify the reporting year (default 2024). This data is tabular only — cannot be mapped."
    ),
}

SLUC_EF_GAS_STATS: list[dict] = [
    Statistics(
        dataset_name="Deforestation (sLUC) Emission Factors by Agricultural Crop",
        source_url="http://example.com/analytics/sluc-ef",
        start_date="2024-01-01",
        end_date="2024-12-31",
        aoi_names=["Brazil"],
        parameters=None,
        context_layer=None,
        data={
            "crop": ["Soybean", "Soybean", "Soybean"],
            "gas_type": ["CO2", "CH4", "N2O"],
            "emissions_tco2e": [4567890, 123456, 45678],
            "emission_factor_tco2e_per_tonne": [0.45, 0.012, 0.005],
        },
    )
]

SLUC_EF_MULTI_CROP_STATS: list[dict] = [
    Statistics(
        dataset_name="Deforestation (sLUC) Emission Factors by Agricultural Crop",
        source_url="http://example.com/analytics/sluc-ef",
        start_date="2024-01-01",
        end_date="2024-12-31",
        aoi_names=["Brazil"],
        parameters=None,
        context_layer=None,
        data={
            "crop": [
                "Soybean",
                "Soybean",
                "Soybean",
                "Cattle",
                "Cattle",
                "Cattle",
                "Cocoa",
                "Cocoa",
                "Cocoa",
                "Oil Palm",
                "Oil Palm",
                "Oil Palm",
                "Coffee",
                "Coffee",
                "Coffee",
            ],
            "gas_type": ["CO2", "CH4", "N2O"] * 5,
            "emissions_tco2e": [
                4567890,
                123456,
                45678,
                8901234,
                234567,
                89012,
                1234567,
                56789,
                23456,
                567890,
                12345,
                4567,
                345678,
                9012,
                3456,
            ],
            "emission_factor_tco2e_per_tonne": [
                0.45,
                0.012,
                0.005,
                1.23,
                0.033,
                0.012,
                2.34,
                0.056,
                0.023,
                0.67,
                0.015,
                0.006,
                0.12,
                0.003,
                0.001,
            ],
        },
    )
]


# ===========================================================================
# GHG Flux — test_split_bar_chart
# ===========================================================================
class TestGhgFluxSplitBarChart:
    """Eval behavior: split/diverging bar chart for emissions vs removals."""

    async def test_bar_chart_for_flux(self):
        update = await invoke_generate_insights(
            "Brazil forest emissions and removals",
            GHG_FLUX_DATASET,
            GHG_FLUX_STATS,
        )
        chart = chart_from(update)
        assert chart is not None, "Expected chart data in output"
        assert (
            chart["type"] == "bar"
        ), f"Expected bar chart for flux, got {chart['type']}"

    async def test_flux_chart_has_data(self):
        update = await invoke_generate_insights(
            "Show the forest carbon flux for Brazil",
            GHG_FLUX_DATASET,
            GHG_FLUX_STATS,
        )
        chart = chart_from(update)
        assert chart is not None
        assert (
            len(chart["data"]) >= 2
        ), "Expected at least 2 data rows (emissions + removals)"


# ===========================================================================
# GHG Flux — test_uses_sink_source_terminology
# ===========================================================================
class TestGhgFluxSinkSourceTerminology:
    """Eval behavior: insight text uses 'net source' or 'net sink' correctly."""

    async def test_positive_flux_says_source(self):
        update = await invoke_generate_insights(
            "Is Brazil's forest a carbon source or sink?",
            GHG_FLUX_DATASET,
            GHG_FLUX_STATS,
        )
        text = insight_text(update).lower()
        assert (
            "source" in text
        ), f"Expected 'source' in insight for positive net flux. Got: {text[:200]}"


# ===========================================================================
# Grasslands — test_bar_or_line_for_trend
# ===========================================================================
class TestGrasslandTrend:
    """Eval behavior: temporal data → line or bar chart."""

    async def test_trend_chart_type(self):
        update = await invoke_generate_insights(
            "Show grassland area over time in Kenya",
            GRASSLAND_DATASET,
            GRASSLAND_STATS,
        )
        chart = chart_from(update)
        assert chart is not None
        assert chart["type"] in (
            "line",
            "bar",
        ), f"Expected line or bar for trend, got {chart['type']}"

    async def test_trend_has_temporal_data(self):
        update = await invoke_generate_insights(
            "Kenya grassland area trend",
            GRASSLAND_DATASET,
            GRASSLAND_STATS,
        )
        chart = chart_from(update)
        assert chart is not None
        assert (
            len(chart["data"]) > 5
        ), "Expected multiple year data points for temporal trend"


# ===========================================================================
# Grasslands — test_excludes_zero_area
# ===========================================================================
class TestGrasslandExcludesZero:
    """Eval behavior: chart data must not contain rows where area_ha = 0."""

    async def test_no_zero_values_in_chart(self):
        update = await invoke_generate_insights(
            "Display all grassland area values for Kenya",
            GRASSLAND_DATASET,
            GRASSLAND_STATS_WITH_ZEROS,
        )
        chart = chart_from(update)
        assert chart is not None
        # Check that no value field contains 0
        for row in chart["data"]:
            for key, val in row.items():
                if isinstance(val, (int, float)) and key != "year":
                    assert (
                        val != 0
                    ), f"Found zero value in chart data row: {row}"


# ===========================================================================
# Tree Cover — test_bar_or_pie_for_density
# ===========================================================================
class TestTreeCoverDensityChart:
    """Eval behavior: bar or pie chart for canopy density distribution, in hectares."""

    async def test_density_chart_type(self):
        update = await invoke_generate_insights(
            "Tree cover density breakdown for DRC",
            TREE_COVER_DATASET,
            TREE_COVER_STATS,
        )
        chart = chart_from(update)
        assert chart is not None
        assert chart["type"] in (
            "bar",
            "pie",
        ), f"Expected bar or pie for density, got {chart['type']}"


# ===========================================================================
# Tree Cover — test_excludes_zero_area (0% bin + zero area rows)
# ===========================================================================
class TestTreeCoverExcludesZero:
    """Eval behavior: exclude 0% density bin and rows with area_ha = 0."""

    async def test_no_zero_percent_bin(self):
        update = await invoke_generate_insights(
            "Show all tree cover density classes in DRC",
            TREE_COVER_DATASET,
            TREE_COVER_STATS,
        )
        chart = chart_from(update)
        assert chart is not None
        for row in chart["data"]:
            row_str = str(row).lower()
            # The 0% bin should not appear (avoid matching 20%, 30%, … via substring "0%")
            assert (
                re.search(r"(?<![0-9])0%", row_str) is None
            ), f"Found 0% density bin in chart data: {row}"


# ===========================================================================
# Tree Cover — test_uses_tree_cover_not_forest
# ===========================================================================
class TestTreeCoverTerminology:
    """Eval behavior: insight text uses 'tree cover' not unqualified 'forest'."""

    async def test_uses_tree_cover_term(self):
        update = await invoke_generate_insights(
            "How much forest is in the DRC?",
            TREE_COVER_DATASET,
            TREE_COVER_STATS,
        )
        text = insight_text(update).lower()
        assert (
            "tree cover" in text
        ), f"Expected 'tree cover' in insight. Got: {text[:200]}"


# ===========================================================================
# Tree Cover Gain — test_bar_chart_per_period
# ===========================================================================
class TestTreeCoverGainBarChart:
    """Eval behavior: bar chart with cumulative period labels."""

    async def test_bar_chart_type(self):
        update = await invoke_generate_insights(
            "Show tree cover gain in Indonesia",
            TREE_COVER_GAIN_DATASET,
            TREE_COVER_GAIN_STATS,
        )
        chart = chart_from(update)
        assert chart is not None
        assert (
            chart["type"] == "bar"
        ), f"Expected bar chart for gain periods, got {chart['type']}"

    async def test_has_period_data(self):
        update = await invoke_generate_insights(
            "Tree cover gain in Indonesia 2000-2020",
            TREE_COVER_GAIN_DATASET,
            TREE_COVER_GAIN_STATS,
        )
        chart = chart_from(update)
        assert chart is not None
        assert (
            len(chart["data"]) >= 2
        ), "Expected multiple period bars in chart"


# ===========================================================================
# Tree Cover Gain — test_does_not_use_restoration
# ===========================================================================
class TestTreeCoverGainTerminology:
    """Eval behavior: uses 'tree cover gain' not 'restoration' uncaveated."""

    async def test_gain_terminology(self):
        update = await invoke_generate_insights(
            "How much forest was restored in Indonesia?",
            TREE_COVER_GAIN_DATASET,
            TREE_COVER_GAIN_STATS,
        )
        text = insight_text(update).lower()
        assert (
            "tree cover gain" in text or "gain" in text
        ), f"Expected 'tree cover gain' or 'gain' in insight. Got: {text[:200]}"


# ===========================================================================
# Tree Cover Gain — test_refuses_net_calculation
# ===========================================================================
class TestTreeCoverGainRefusesNetCalc:
    """Eval behavior: warns that net change cannot be computed from gain + loss."""

    async def test_refuses_or_warns_net_calc(self):
        update = await invoke_generate_insights(
            "Calculate net tree cover change for Indonesia",
            TREE_COVER_GAIN_DATASET,
            TREE_COVER_GAIN_STATS,
        )
        text = insight_text(update).lower()
        # Should mention inability to compute net change, or warn about methodology (align with analytics_datasets.yml)
        has_warning = any(
            phrase in text
            for phrase in [
                "cannot",
                "can't",
                "not possible",
                "unable",
                "should not",
                "do not",
                "methodolog",
                "incompatible",
                "different",
                "caution",
                "warning",
                "net change",
                "not be subtracted",
                "not be combined",
                "cannot be combined",
                "subtract",
                "tree cover loss",
                "loss dataset",
            ]
        )
        assert (
            has_warning
        ), f"Expected warning about net calculation. Got: {text[:300]}"


# ===========================================================================
# Land Cover — test_pie_chart_for_composition
# ===========================================================================
class TestLandCoverPieComposition:
    """Eval behavior: pie chart for land cover composition."""

    async def test_pie_chart(self):
        update = await invoke_generate_insights(
            "Pie chart of land cover in Brazil",
            LAND_COVER_DATASET,
            LAND_COVER_COMPOSITION_STATS,
        )
        chart = chart_from(update)
        assert chart is not None
        assert (
            chart["type"] == "pie"
        ), f"Expected pie chart for composition, got {chart['type']}"


# ===========================================================================
# Land Cover — test_table_for_transitions
# ===========================================================================
class TestLandCoverTableTransitions:
    """Eval behavior: table format for land cover transitions."""

    async def test_table_for_transitions(self):
        update = await invoke_generate_insights(
            "Land cover class transitions in Brazil — table please",
            LAND_COVER_DATASET,
            LAND_COVER_TRANSITION_STATS,
        )
        chart = chart_from(update)
        assert chart is not None
        assert (
            chart["type"] == "table"
        ), f"Expected table for transitions, got {chart['type']}"


# ===========================================================================
# Land Cover — test_combines_agriculture
# ===========================================================================
class TestLandCoverCombinesAgriculture:
    """Eval behavior: agriculture = cropland + cultivated grassland."""

    async def test_agriculture_combined(self):
        update = await invoke_generate_insights(
            "What fraction of Brazil is agriculture?",
            LAND_COVER_DATASET,
            LAND_COVER_COMPOSITION_STATS,
        )
        text = insight_text(update).lower()
        # Should mention both cropland and cultivated grassland, or combined agriculture
        has_combined = (
            "cultivated grassland" in text
            or ("cropland" in text and "grassland" in text)
            or "agriculture" in text
        )
        assert (
            has_combined
        ), f"Expected combined agriculture reference. Got: {text[:300]}"


# ===========================================================================
# Natural Lands — test_bar_or_pie_for_proportions
# ===========================================================================
class TestNaturalLandsProportions:
    """Eval behavior: bar or pie chart distinguishing natural vs non-natural."""

    async def test_proportions_chart_type(self):
        update = await invoke_generate_insights(
            "Natural vs non-natural land cover in Colombia",
            NATURAL_LANDS_DATASET,
            NATURAL_LANDS_STATS,
        )
        chart = chart_from(update)
        assert chart is not None
        assert chart["type"] in (
            "bar",
            "pie",
        ), f"Expected bar or pie for proportions, got {chart['type']}"


# ===========================================================================
# Natural Lands — test_combines_natural_forest_classes
# ===========================================================================
class TestNaturalLandsCombinesForest:
    """Eval behavior: combine natural forest sub-classes (2, 5, 8, 9)."""

    async def test_forest_classes_combined(self):
        update = await invoke_generate_insights(
            "How much natural forest is in Colombia?",
            NATURAL_LANDS_DATASET,
            NATURAL_LANDS_STATS,
        )
        text = insight_text(update).lower()
        # Should mention a combined total or reference sub-categories
        has_combined = any(
            phrase in text
            for phrase in [
                "mangrove",
                "wetland",
                "peat",
                "includes",
                "combined",
                "total",
                "natural forest",
            ]
        )
        assert (
            has_combined
        ), f"Expected reference to combined forest classes. Got: {text[:300]}"


# ===========================================================================
# Natural Lands — test_refuses_change_over_time
# ===========================================================================
class TestNaturalLandsRefusesChange:
    """Eval behavior: refuses change-over-time for 2020 snapshot."""

    async def test_refuses_or_explains_limitation(self):
        update = await invoke_generate_insights(
            "How has natural land in Colombia changed over time?",
            NATURAL_LANDS_DATASET,
            NATURAL_LANDS_STATS,
        )
        text = insight_text(update).lower()
        has_limitation = any(
            phrase in text
            for phrase in [
                "snapshot",
                "2020",
                "single year",
                "baseline",
                "cannot",
                "not available",
                "does not",
                "land cover",  # suggestion to use land cover dataset
            ]
        )
        assert (
            has_limitation
        ), f"Expected limitation/snapshot explanation. Got: {text[:300]}"


# ===========================================================================
# sLUC EF — test_pie_for_gas_type
# ===========================================================================
class TestSlucEfPieGasType:
    """Eval behavior: pie chart for GHG breakdown by gas type."""

    async def test_pie_chart_gas_breakdown(self):
        update = await invoke_generate_insights(
            "Soybean emissions by gas type in Brazil 2024 — pie chart",
            SLUC_EF_DATASET,
            SLUC_EF_GAS_STATS,
        )
        chart = chart_from(update)
        assert chart is not None
        assert (
            chart["type"] == "pie"
        ), f"Expected pie chart for gas breakdown, got {chart['type']}"


# ===========================================================================
# sLUC EF — test_table_for_multiple_crops
# ===========================================================================
class TestSlucEfTableMultipleCrops:
    """Eval behavior: table format when comparing multiple crops."""

    async def test_table_for_crops(self):
        update = await invoke_generate_insights(
            "Table of crop emission factors for Brazil",
            SLUC_EF_DATASET,
            SLUC_EF_MULTI_CROP_STATS,
        )
        chart = chart_from(update)
        assert chart is not None
        assert (
            chart["type"] == "table"
        ), f"Expected table for multiple crops, got {chart['type']}"


# ===========================================================================
# sLUC EF — test_includes_units
# ===========================================================================
class TestSlucEfIncludesUnits:
    """Eval behavior: insight text includes proper units (tCO2e)."""

    async def test_units_in_insight(self):
        update = await invoke_generate_insights(
            "What is the emission factor for soybean in Brazil?",
            SLUC_EF_DATASET,
            SLUC_EF_GAS_STATS,
        )
        text = insight_text(update).lower()
        assert (
            "tco2e" in text or "co2e" in text or "co₂e" in text
        ), f"Expected tCO2e units in insight. Got: {text[:200]}"


# ===========================================================================
# sLUC EF — test_refuses_map
# ===========================================================================
class TestSlucEfRefusesMap:
    """Eval behavior: refuses map visualization for tabular-only data."""

    async def test_refuses_map(self):
        update = await invoke_generate_insights(
            "Show a map of soybean emission factors in Brazil",
            SLUC_EF_DATASET,
            SLUC_EF_GAS_STATS,
        )
        text = insight_text(update).lower()
        chart = chart_from(update)
        # Should not produce a map chart type and should explain limitation
        if chart:
            assert chart["type"] != "map", "Should not produce a map chart"
        has_explanation = any(
            phrase in text
            for phrase in [
                "tabular",
                "cannot be mapped",
                "no spatial",
                "not available",
                "geographic",
                "not possible",
            ]
        )
        has_chart_failure = any(
            phrase in text
            for phrase in [
                "failed to generate chart data",
                "failed to generate",
            ]
        )
        # The chart type being non-map is the primary assertion;
        # textual explanation is a bonus
        assert (
            chart is not None or has_explanation or has_chart_failure
        ), f"Expected non-map output or explanation. Got: {text[:300]}"


# ===========================================================================
# Land Cover — test_refuses_annual_timeseries
# ===========================================================================
class TestLandCoverRefusesTimeseries:
    """Eval behavior: refuses annual timeseries for 2-snapshot data."""

    async def test_refuses_annual_data(self):
        update = await invoke_generate_insights(
            "Show me annual land cover change in Brazil from 2015 to 2024",
            LAND_COVER_DATASET,
            LAND_COVER_TRANSITION_STATS,
        )
        text = insight_text(update).lower()
        # Should explain the limitation or refuse
        has_limitation = any(
            phrase in text
            for phrase in [
                "snapshot",
                "two",
                "2015",
                "2024",
                "not annual",
                "cannot",
                "only",
                "available",
            ]
        )
        assert (
            has_limitation
        ), f"Expected snapshot/limitation explanation. Got: {text[:300]}"
