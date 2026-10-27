"""Provides all info for the request builder, given a dataset_id

Given a dataset_id, this provides:
- the URL to POST to
- payload shape
- time window (when start/end isn't specified)
- how to distinguish between datasets that use the same URL (TCL/TCLF for example)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# How a dataset's payload is shaped beyond the mandatory ``aoi`` block.
#   none        AOI only
#   date        start_date/end_date only (zeno's Integrated Alerts branch)
#   year        start_year/end_year
#   loss        start_year/end_year + forest_filter + intersections + canopy_cover
#   gain        start_year/end_year snapped to 5-year buckets + forest_filter
#   canopy      canopy_cover only
#   extent      forest_filter + canopy_cover
#   unsupported recognised, but not buildable here yet
PayloadStyle = str

DEFAULT_CANOPY_COVER = 30

SNAPSHOT_PATH = Path(__file__).resolve().parents[3] / "cases" / "zeno_catalog.json"

# maps dataset_id to payload shape. Not in any YAML: zeno builds these in code.
PAYLOAD_STYLES: dict[str, PayloadStyle] = {
    "1": "none",  # land cover
    "2": "year",  # grasslands
    "3": "none",  # SBTN natural lands
    "4": "loss",  # tree cover loss
    "5": "gain",  # tree cover gain — years snap to 5-year buckets
    "6": "canopy",  # carbon flux
    "7": "extent",  # tree cover
    "8": "loss",  # tree cover loss by dominant driver
    "9": "unsupported",  # sLUC — needs the 42-crop crop_types list (1-103)
    "10": "loss",  # tree cover loss from fires
    "11": "date",  # integrated alerts
    "12": "none",  # LGMS
}

# TCL, drivers, and TCLF share an endpoint but have different intersections
INTERSECTIONS: dict[str, tuple[str, ...]] = {
    "8": ("driver",),
    "10": ("fire",),
}


@dataclass(frozen=True)
class Dataset:
    """One dataset's analytics contract."""

    dataset_id: str
    name: str
    endpoint: str  # from cases/zeno_catalog.json
    style: PayloadStyle  # defined above
    start_date: str  # from cases/zeno_catalog.json
    end_date: str | None = None  # from cases/zeno_catalog.json
    fixed: bool = False
    intersections: tuple[str, ...] = ()  # defined above


class CatalogError(Exception):
    """The snapshot is missing or cannot describe a dataset's request."""


@lru_cache(maxsize=1)
def datasets() -> dict[str, Dataset]:
    """Build the request table from the committed snapshot.

    A function, not a module constant, so the snapshot is read on first use
    rather than at import: a missing or corrupt snapshot then surfaces as a
    ``CatalogError`` from the prefetch that needed it, not as an import failure
    in tooling that never touches the analytics API.

    Cached: the snapshot is a committed file, immutable for a run's lifetime.
    A dataset the snapshot no longer carries is simply absent, so
    ``build_request`` fails loudly on it rather than using a stale endpoint
    """
    try:
        raw = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CatalogError(f"cannot read {SNAPSHOT_PATH}: {exc}") from exc

    table: dict[str, Dataset] = {}
    for entry in raw.get("datasets") or []:
        dataset_id = str(entry.get("dataset_id", "")).strip()
        endpoint = entry.get("analytics_api_endpoint")
        start_date = entry.get("start_date")
        if not dataset_id or not endpoint or not start_date:
            # catalog entry with no endpoint or start/end date can't be requested.
            continue
        table[dataset_id] = Dataset(
            dataset_id=dataset_id,
            name=str(entry.get("dataset_name") or ""),
            endpoint=str(endpoint),
            style=PAYLOAD_STYLES.get(dataset_id, "unsupported"),
            start_date=str(start_date),
            end_date=str(entry["end_date"]) if entry.get("end_date") else None,
            fixed=bool(entry.get("content_date_fixed")),
            intersections=INTERSECTIONS.get(dataset_id, ()),
        )
    if not table:
        raise CatalogError(
            f"{SNAPSHOT_PATH} carries no usable datasets; "
            "re-run tools/sync_zeno_catalog.py"
        )
    return table


# expected.aoi_source -> the analytics API's aoi.type.
AOI_TYPES: dict[str, str] = {
    "gadm": "admin",
    "kba": "key_biodiversity_area",
    "wdpa": "protected_area",
    "landmark": "indigenous_land",
}


def dataset_for(dataset_id: str) -> Dataset | None:
    return datasets().get(str(dataset_id).strip())
