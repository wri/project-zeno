"""The columns each dataset's rows have, for the charting skill.

A model that writes code against `rows.csv` needs the column names, their
types and units before it has the rows. The analytics API is the only
authority on them, so they are captured from it: `refresh` pulls each
dataset for one country, once plain and once per context layer, and
records each column's type. The result is checked in as `columns.json`, so
building the skill needs no network. Refresh it when the analytics API or
the catalog changes:

    uv run python -m src.mcp.columns
"""

import asyncio
import json
from datetime import date
from pathlib import Path

from src.agent.datasets.handlers.analytics_handler import (
    LAND_COVER_CHANGE_ID,
    AnalyticsHandler,
)
from src.mcp.datasets import available_datasets

COLUMNS_FILE = Path(__file__).parent / "columns.json"

# One country every dataset covers.
SAMPLE_AREA = {
    "source": "gadm",
    "src_id": "BRA",
    "name": "Brazil",
    "subtype": "country",
}

# What a column holds, from the catalog's descriptions. Units come from the
# name's suffix (`unit_of`).
COLUMN_NOTES = {
    "aoi_id": "The area's id at the analytics API: a GADM id without its version suffix (BRA.14 for gadm:BRA.14_1), or the source's id.",
    "aoi_type": "The kind of area: admin, protected_area, key_biodiversity_area or indigenous_land.",
    "name": "The area's name, added by GNW.",
    "area_ha": "Area.",
    "year": "The year the value is for.",
    "tree_cover_loss_year": "The year the loss was detected.",
    "carbon_emissions_MgCO2e": "Greenhouse gas emissions from the loss.",
    "land_cover_class": "The land cover class.",
    "land_cover_class_start": "The land cover class in the first year.",
    "land_cover_class_end": "The land cover class in the last year.",
    "natural_lands_class": "The SBTN Natural Lands class in 2020.",
    "tree_cover_gain_period": "The period the gain is cumulative over, e.g. 2000-2020.",
    "carbon_net_flux_Mg_CO2e": "Net flux: emissions minus removals. Negative is a sink, positive a source. One value for the dataset's whole period.",
    "carbon_gross_emissions_Mg_CO2e": "Gross emissions from forest disturbance, over the dataset's period.",
    "carbon_gross_removals_Mg_CO2e": "Gross removals by forest growth, over the dataset's period.",
    "tree_cover_loss_driver": "The dominant driver of the loss.",
    "tree_cover_loss_from_fires_area_ha": "Tree cover loss caused by fire.",
    "tree_cover_loss_non_fires_area_ha": "Tree cover loss from all other causes.",
    "crop_type": "The agricultural crop.",
    "gas_type": "The greenhouse gas.",
    "emissions_factor_tCO2e_per_tonne_production": "Emissions from land use change per tonne of the crop produced.",
    "emissions_tCO2e": "Emissions from land use change.",
    "production_tonnes": "Crop production.",
    "alert_date": "The date of the alert, YYYY-MM-DD.",
    "alert_confidence": "The alert's confidence: low, high, or highest (detected by several systems).",
}

_UNITS = (
    ("_tco2e_per_tonne_production", "tCO2e/t"),
    ("_tco2e_per_tonne", "tCO2e/t"),
    ("_mg_co2e", "MgCO2e"),
    ("_mgco2e", "MgCO2e"),
    ("_tco2e", "tCO2e"),
    ("_tonnes", "t"),
    ("_ha", "ha"),
    ("_km2", "km²"),
    ("_pct", "%"),
    ("_percent", "%"),
)


def unit_of(column: str) -> str:
    lower = column.lower()
    return next(
        (unit for suffix, unit in _UNITS if lower.endswith(suffix)), ""
    )


def _type_of(values: list) -> str:
    present = [value for value in values if value is not None]
    if not present:
        return "null"
    kinds = {type(value) for value in present}
    if kinds <= {bool}:
        return "boolean"
    if kinds <= {int}:
        return "integer"
    if kinds <= {int, float}:
        return "number"
    return "string"


def _variants(ds: dict) -> list[tuple[str, dict, bool]]:
    """(variant name, dataset fields, change over time) to capture."""
    base = {"dataset_id": ds["dataset_id"], "dataset_name": ds["dataset_name"]}
    variants = [("default", base, False)]
    for layer in ds.get("context_layers") or []:
        variants.append(
            (
                f"context_layer={layer['value']}",
                {**base, "context_layer": layer["value"]},
                False,
            )
        )
    if ds["dataset_id"] == LAND_COVER_CHANGE_ID:
        variants.append(("change_over_time", base, True))
    return variants


def _dates(ds: dict) -> tuple[str, str]:
    """The dataset's last full year, or its whole range when shorter."""
    end = ds.get("end_date") or date.today().isoformat()
    year = int(end[:4]) - 1
    start = max(str(ds.get("start_date") or end), f"{year}-01-01")
    return start, end


async def capture() -> dict:
    handler = AnalyticsHandler()
    captured: dict = {}
    for ds in available_datasets():
        start, end = _dates(ds)
        variants = {}
        for name, dataset, change_over_time in _variants(ds):
            result = await handler.pull_data(
                query="",
                dataset=dataset,
                start_date=start,
                end_date=end,
                change_over_time_query=change_over_time,
                aois=[dict(SAMPLE_AREA)],
            )
            if not result.success or not isinstance(result.data, dict):
                variants[name] = {"error": (result.message or "")[:300]}
                continue
            # A column can be a single null where the API has no values.
            variants[name] = {
                "columns": {
                    column: _type_of(
                        values if isinstance(values, list) else [values]
                    )
                    for column, values in result.data.items()
                }
            }
        captured[str(ds["dataset_id"])] = variants
    return captured


def load() -> dict:
    """The checked-in columns, by dataset id (str) and variant."""
    return json.loads(COLUMNS_FILE.read_text(encoding="utf-8"))


def refresh() -> None:
    captured = asyncio.run(capture())
    COLUMNS_FILE.write_text(
        json.dumps(captured, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    refresh()
    print(f"Wrote {COLUMNS_FILE}")
