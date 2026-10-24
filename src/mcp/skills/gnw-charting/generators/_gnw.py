"""Stand-ins for the zeno modules GNW's chart generators import, so the
generators in this folder run outside zeno: InsightChart (the chart spec),
the dataset ids, and the English chart titles and labels. Written by
src/mcp/skill.py from zeno's own definitions; do not edit.
"""

import math
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

FOREST_CARBON_FLUX_ID = 6
GRASSLANDS_ID = 2
INTEGRATED_ALERTS_ID = 11
LAND_COVER_CHANGE_ID = 1
LAND_GHG_INVENTORY_ID = 12
NATURAL_LANDS_ID = 3
SLUC_EMISSION_FACTORS_ID = 9
TREE_COVER_GAIN_ID = 5
TREE_COVER_ID = 7
TREE_COVER_LOSS_BY_DRIVER_ID = 8
TREE_COVER_LOSS_BY_FIRES_ID = 10
TREE_COVER_LOSS_ID = 4

# Message key -> English text, from zeno's src/agent/i18n.py.
MESSAGES = {
    "charts.tcl.annual_loss": "Annual Tree Cover Loss",
    "charts.tcl.annual_emissions": "Annual GHG Emissions from Tree Cover Loss",
    "charts.integrated_alerts.by_confidence": "Integrated Deforestation Alerts by Confidence",
    "charts.lgms.full_detail": "Net GHG Flux — Full Detail",
    "charts.lgms.by_category": "Net GHG Flux by Category",
    "charts.lgms.summary": "Net GHG Flux Summary",
    "charts.lgms.annual_average": "Net GHG Flux — Annual Average",
    "charts.land_cover.composition": "Land Cover Composition",
    "charts.land_cover.transitions": "Land Cover Transitions",
    "charts.natural_lands.by_class": "Natural Lands Area by Class",
    "charts.grasslands.by_year": "Natural and Semi-Natural Grassland Extent by Year",
    "charts.tree_cover_gain.by_period": "Tree Cover Gain by Period",
    "charts.forest_flux.net": "Forest Greenhouse Gas Net Flux",
    "charts.tree_cover.extent": "Tree Cover Extent",
    "charts.tcl_by_driver.by_driver": "Tree Cover Loss by Dominant Driver",
    "charts.sluc.by_gas": "Deforestation Emissions by Gas Type (tCO2e)",
    "charts.sluc.by_crop": "Deforestation Emissions by Crop (tCO2e)",
    "charts.tcl_by_fires.annual_split": "Annual Tree Cover Loss from Fires vs Other Causes",
    "charts.tcl_by_fires.split": "Tree Cover Loss from Fires vs Other Causes",
    "charts.label.gross_emissions": "Gross emissions",
    "charts.label.gross_removals": "Gross removals",
    "charts.label.net_flux": "Net flux",
    "charts.label.fires": "Fires",
    "charts.label.other": "Other",
    "charts.tcl_natural_forest.annual_split": "Annual Tree Cover Loss in Natural Forest and Other Tree Cover",
    "charts.label.natural_forest": "Natural forest",
    "charts.label.other_tree_cover": "Other tree cover"
}


def _json_safe(value):
    """NaN and Inf as None, as zeno's InsightChart stores them."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


@dataclass
class InsightChart:
    """A chart spec and the rows it draws: zeno's InsightChart."""

    title: str
    chart_type: str
    position: int = 0
    x_axis: str = ""
    y_axis: str = ""
    color_field: str = ""
    stack_field: str = ""
    group_field: str = ""
    series_fields: List[str] = field(default_factory=list)
    chart_data: List[dict] = field(default_factory=list)
    insight: str = ""
    dataset_id: Optional[int] = None
    color_map: Dict[str, str] = field(default_factory=dict)
    series_color: Optional[str] = None
    divergent_colors: Optional[Dict[str, str]] = None

    def __post_init__(self):
        self.chart_data = [_json_safe(row) for row in self.chart_data]

    def model_dump(self, exclude=()):
        return {
            key: value
            for key, value in asdict(self).items()
            if key not in exclude
        }


def text(key):
    """A message key's English text; the key itself when it has none."""
    return MESSAGES.get(key) or key


def localise(charts, generator):
    """Message keys to English text, as zeno's curated.py does."""
    for chart in charts:
        chart.title = text(chart.title)
        for column in generator.label_fields:
            for row in chart.chart_data:
                if column in row:
                    row[column] = text(row[column])
        if generator.label_series:
            names = {key: text(key) for key in chart.series_fields}
            if len(set(names.values())) != len(names):
                raise ValueError(f"Series names are not unique: {names}")
            chart.series_fields = [names[key] for key in chart.series_fields]
            chart.chart_data = [
                {names.get(key, key): value for key, value in row.items()}
                for row in chart.chart_data
            ]
            chart.color_map = {
                names.get(key, key): color
                for key, color in chart.color_map.items()
            }
