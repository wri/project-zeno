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

from src.agent.datasets.config import DATASETS
from src.agent.datasets.handlers.analytics_handler import (
    LAND_COVER_CHANGE_ID,
    NATURAL_LANDS_ID,
)
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


def _catalog_classes(dataset_id: int) -> dict[str, str]:
    """The slug of each class of a dataset, keyed by its folded English
    label in the catalog."""
    dataset = next(d for d in DATASETS if d["dataset_id"] == dataset_id)
    return {
        _fold(category["label_en"]): category["slug"]
        for category in dataset.get("categories") or []
    }


def _areas_by_slug(
    rows: Iterable[dict], label_column: str, classes: dict[str, str]
) -> dict[str, float]:
    """The area of each class, keyed by its catalog slug. A label that the
    catalog does not have raises: a group that leaves it out would give a
    wrong figure with no error."""
    areas: dict[str, float] = {}
    for row in rows:
        area = row.get("area_ha")
        label = row.get(label_column)
        if area is None or label is None:
            continue
        slug = classes.get(_fold(label))
        if slug is None:
            raise ValueError(
                f"Unknown {label_column} {label!r}: not in the catalog"
            )
        areas[slug] = areas.get(slug, 0.0) + float(area)
    return areas


def _share(part: float, whole: float) -> str:
    return f", {number(100 * part / whole)}% of the total" if whole else ""


def _require_slugs(dataset_id: int, *groups: Iterable[str]) -> None:
    """Fail at import when a group names a slug that the catalog does not
    have, so that a catalog change cannot make a group 0 ha."""
    known = set(_catalog_classes(dataset_id).values())
    for group in groups:
        missing = set(group) - known
        if missing:
            raise RuntimeError(
                f"Dataset {dataset_id} has no classes {sorted(missing)}"
            )


# --- land cover composition -------------------------------------------------

# The code instructions: for agriculture, combine cropland and cultivated
# grasslands into one category.
AGRICULTURE = ("cropland", "cultivated_grasslands")
_LAND_COVER_CLASSES = _catalog_classes(LAND_COVER_CHANGE_ID)
_require_slugs(LAND_COVER_CHANGE_ID, AGRICULTURE)


def land_cover_facts(rows: list[dict]) -> list[str]:
    areas = _areas_by_slug(rows, "land_cover_class", _LAND_COVER_CLASSES)
    total = math.fsum(areas.values())
    if not total:
        return []
    agriculture = math.fsum(areas.get(slug, 0.0) for slug in AGRICULTURE)
    return [
        "Agriculture (cropland and cultivated grasslands): "
        f"{number(agriculture)} ha{_share(agriculture, total)}."
    ]


# --- natural lands ----------------------------------------------------------

# The groups of the catalog's classes (sbtn_natural_lands_map.yml, the
# description and the code instructions). Each catalog class is in one
# group; the import fails when a new class is in none.
NATURAL = (
    "natural_forests",
    "natural_peat_forests",
    "natural_peat_short_vegetation",
    "mangroves",
    "wet_natural_forests",
    "wet_natural_short_vegetation",
    "natural_short_vegetation",
    "natural_water",
    "bare",
    "snow",
)
NON_NATURAL = (
    "crop",
    "built",
    "non_natural_tree_cover",
    "non_natural_short_vegetation",
    "wet_non_natural_tree_cover",
    "non_natural_peat_tree_cover",
    "wet_non_natural_short_vegetation",
    "non_natural_peat_short_vegetation",
    "non_natural_water",
    "non_natural_bare",
)
# "Other" in the catalog; the analyser gives class 1 and unknown codes as
# "Unclassified". Neither natural nor non-natural.
UNCLASSIFIED = ("other",)
# The code instructions: natural forest is natural forest, mangrove,
# wetland natural forest and natural peat forest.
NATURAL_FOREST = (
    "natural_forests",
    "mangroves",
    "wet_natural_forests",
    "natural_peat_forests",
)
_NATURAL_LANDS_CLASSES = {
    **_catalog_classes(NATURAL_LANDS_ID),
    "unclassified": "other",
}
_require_slugs(NATURAL_LANDS_ID, NATURAL, NON_NATURAL, UNCLASSIFIED)
_unsorted = set(_NATURAL_LANDS_CLASSES.values()) - {
    *NATURAL,
    *NON_NATURAL,
    *UNCLASSIFIED,
}
if _unsorted:
    raise RuntimeError(
        f"Natural lands classes in no group: {sorted(_unsorted)}"
    )


def natural_lands_facts(rows: list[dict]) -> list[str]:
    areas = _areas_by_slug(rows, "natural_lands_class", _NATURAL_LANDS_CLASSES)
    total = math.fsum(areas.values())
    if not total:
        return []
    natural = math.fsum(areas.get(slug, 0.0) for slug in NATURAL)
    non_natural = math.fsum(areas.get(slug, 0.0) for slug in NON_NATURAL)
    unclassified = math.fsum(areas.get(slug, 0.0) for slug in UNCLASSIFIED)
    forest = math.fsum(areas.get(slug, 0.0) for slug in NATURAL_FOREST)
    facts = [
        f"Natural land: {number(natural)} ha{_share(natural, total)}.",
        f"Non-natural land: {number(non_natural)} ha"
        f"{_share(non_natural, total)}.",
    ]
    if unclassified:
        facts.append(
            "Unclassified land (neither natural nor non-natural): "
            f"{number(unclassified)} ha{_share(unclassified, total)}."
        )
    facts.append(
        "Natural forest (natural forests, mangroves, wetland natural "
        f"forests, natural peat forests): {number(forest)} ha"
        f"{_share(forest, total)}."
    )
    return facts


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


# --- tree cover gain --------------------------------------------------------

GAIN_PERIOD = "tree_cover_gain_period"


def gain_facts(rows: list[dict]) -> list[str]:
    """The total gain and the period that it covers. The handler rounds
    the request to 5-year periods, and the API returns only those periods:
    the total is the gain of the pulled periods, not always 2000 to 2020."""
    periods = [
        (str(r[GAIN_PERIOD]), float(r["area_ha"]))
        for r in rows
        if r.get(GAIN_PERIOD) is not None and r.get("area_ha") is not None
    ]
    if not periods:
        return []
    bounds = sorted(
        bound for period, _ in periods for bound in period.split("-")
    )
    total = math.fsum(area for _, area in periods)
    return [
        f"Tree cover gain from {bounds[0]} to {bounds[-1]} (the sum of "
        f"the {len(periods)} pulled 5-year periods): {number(total)} ha."
    ]


VIEW_FACTS: dict[str, Callable[[list[dict]], list[str]]] = {
    "tcl_by_driver.by_driver": driver_facts,
    "land_cover.composition": land_cover_facts,
    "natural_lands.by_class": natural_lands_facts,
    "forest_flux.net": forest_flux_facts,
    "tcl_by_fires.annual_split": fires_facts,
    "tree_cover_gain.by_period": gain_facts,
}
