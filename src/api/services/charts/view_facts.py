"""Facts of a curated view that its chart cannot give.

Each function reads the pulled rows of one view and returns sentences for
a model to copy: groups that the dataset's code instructions name, or a
class that the chart leaves out. The generic facts of a chart
(`facts.measure_facts`) cover totals, extremes, changes and ranks.

`VIEW_FACTS` maps a view id to its function. The curated tool message of
the agent gives these facts under the chart (docs/curated-charts-first-plan.md).
"""

import math
from typing import Callable, Iterable

from src.api.services.charts.facts import number
from src.api.services.charts.tcl_by_driver import driver_facts


def _fold(label: str) -> str:
    """One spelling for a class label: the analytics API and the catalog
    write some classes differently ("Wetland natural forests" and "Wet
    natural forests", "Built-up" and "Built", "Cropland" and "Crop")."""
    text = " ".join(str(label).replace("&", " and ").split()).casefold()
    for long, short in (
        ("wetland ", "wet "),
        ("built-up", "built"),
        ("cropland", "crop"),
    ):
        text = text.replace(long, short)
    return text


def _areas(rows: Iterable[dict], label_column: str) -> dict[str, float]:
    """The area of each class, keyed by its folded label."""
    areas: dict[str, float] = {}
    for row in rows:
        area = row.get("area_ha")
        label = row.get(label_column)
        if area is None or label is None:
            continue
        key = _fold(label)
        areas[key] = areas.get(key, 0.0) + float(area)
    return areas


def _share(part: float, whole: float) -> str:
    return f", {number(100 * part / whole)}% of the total" if whole else ""


# --- land cover composition -------------------------------------------------

# The code instructions: for agriculture, combine cropland and cultivated
# grasslands into one category.
AGRICULTURE = ("crop", "cultivated grasslands")


def land_cover_facts(rows: list[dict]) -> list[str]:
    areas = _areas(rows, "land_cover_class")
    total = math.fsum(areas.values())
    if not total:
        return []
    agriculture = math.fsum(areas.get(key, 0.0) for key in AGRICULTURE)
    return [
        "Agriculture (cropland and cultivated grasslands): "
        f"{number(agriculture)} ha{_share(agriculture, total)}."
    ]


# --- natural lands ----------------------------------------------------------

# The code instructions: natural forest is natural forest, mangrove,
# wetland natural forest and natural peat forest.
NATURAL_FOREST = (
    "natural forests",
    "mangroves",
    "wet natural forests",
    "natural peat forests",
)
# The classes that are not natural, other than the "non-natural ..." ones.
OTHER_NON_NATURAL = ("crop", "built", "other")


def is_natural(folded_label: str) -> bool:
    return (
        "non-natural" not in folded_label
        and folded_label not in OTHER_NON_NATURAL
    )


def natural_lands_facts(rows: list[dict]) -> list[str]:
    areas = _areas(rows, "natural_lands_class")
    total = math.fsum(areas.values())
    if not total:
        return []
    natural = math.fsum(a for key, a in areas.items() if is_natural(key))
    forest = math.fsum(areas.get(key, 0.0) for key in NATURAL_FOREST)
    return [
        f"Natural land: {number(natural)} ha{_share(natural, total)}.",
        f"Non-natural land: {number(total - natural)} ha"
        f"{_share(total - natural, total)}.",
        "Natural forest (natural forests, mangroves, wetland natural "
        f"forests, natural peat forests): {number(forest)} ha"
        f"{_share(forest, total)}.",
    ]


# --- forest flux ------------------------------------------------------------

FLUX_COLUMNS = (
    ("Gross emissions", "carbon_gross_emissions_Mg_CO2e"),
    ("Gross removals", "carbon_gross_removals_Mg_CO2e"),
    ("Net flux", "carbon_net_flux_Mg_CO2e"),
)


def forest_flux_facts(rows: list[dict]) -> list[str]:
    """The three totals, with removals as a negative value as the chart
    shows them, and whether the area is a net sink or a net source."""
    sums = {}
    for label, column in FLUX_COLUMNS:
        values = [float(r[column]) for r in rows if r.get(column) is not None]
        if values:
            sums[label] = math.fsum(values)
    if not sums:
        return []
    if "Gross removals" in sums:
        sums["Gross removals"] = -abs(sums["Gross removals"])
    facts = [
        f"{label} from 2001 to 2025: {number(value)} MgCO2e."
        for label, value in sums.items()
    ]
    net = sums.get("Net flux")
    if net is not None and net != 0:
        kind = "a net sink" if net < 0 else "a net source"
        facts.append(
            f"The area is {kind} (removals {'>' if net < 0 else '<'} emissions)."
        )
    return facts


# --- tree cover loss from fires ---------------------------------------------

FIRES = "tree_cover_loss_from_fires_area_ha"
OTHER = "tree_cover_loss_non_fires_area_ha"


def fires_facts(rows: list[dict]) -> list[str]:
    """The share of fires in the loss of the whole pulled period."""
    fires = math.fsum(
        float(r[FIRES]) for r in rows if r.get(FIRES) is not None
    )
    other = math.fsum(
        float(r[OTHER]) for r in rows if r.get(OTHER) is not None
    )
    total = fires + other
    if not total:
        return []
    return [
        f"Loss from fires over the pulled period: {number(fires)} ha, "
        f"{number(100 * fires / total)}% of all loss ({number(total)} ha)."
    ]


VIEW_FACTS: dict[str, Callable[[list[dict]], list[str]]] = {
    "tcl_by_driver.by_driver": driver_facts,
    "land_cover.composition": land_cover_facts,
    "natural_lands.by_class": natural_lands_facts,
    "forest_flux.net": forest_flux_facts,
    "tcl_by_fires.annual_split": fires_facts,
}
