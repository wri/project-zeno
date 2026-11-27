"""Rank the areas of a pull by one measure, for a ranked bar chart.

Pure functions, with no dataset names: the caller names the value column.
A generator turns the pulled rows and the areas of the pull into the rows
of a chart (docs: PZB-1728). The area ids are the ids that the analytics
API returns (the GADM id without its version suffix), so the ids of the
selection go through `format_id` first.
"""

from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from src.shared.geocoding_helpers import format_id

# Decimals kept in a sum and in a share: removes float noise from adding
# many rows without hiding a real difference.
VALUE_DECIMALS = 2

# The only source whose areas are known not to overlap when they are at one
# level and have no area inside another (`shares_allowed`).
NON_OVERLAPPING_SOURCE = "gadm"


@dataclass(frozen=True)
class RankedArea:
    """One area of the pull. `id` is the id of the pulled rows."""

    id: str
    name: str
    parent: Optional[str]
    source: str


def split_name(full_name: str) -> tuple[str, Optional[str]]:
    """ "Bom Jesus, Piauí, Brazil" gives ("Bom Jesus", "Piauí"); a name with
    one part gives (name, None)."""
    parts = [part.strip() for part in full_name.split(",")]
    parts = [part for part in parts if part]
    if not parts:
        return full_name, None
    return parts[0], parts[1] if len(parts) > 1 else None


def build_ranked_areas(
    ids: Sequence[str],
    names: Sequence[str],
    sources: Sequence[str],
    id_to_name: Optional[dict] = None,
) -> list[RankedArea]:
    """The areas of a pull from its parallel lists (`aoi_ids`, `aoi_names`,
    `aoi_sources`). `id_to_name` is the pull's map from row id to name; it
    gives the name, and the full name gives the parent. Raises when the
    lists differ in length or an id repeats."""
    if not (len(ids) == len(names) == len(sources)):
        raise ValueError(
            "The areas of the pull do not agree: "
            f"{len(ids)} ids, {len(names)} names, {len(sources)} sources"
        )
    id_to_name = id_to_name or {}
    areas = []
    for raw_id, full_name, source in zip(ids, names, sources):
        area_id = format_id(raw_id)
        first, parent = split_name(full_name)
        areas.append(
            RankedArea(
                area_id, id_to_name.get(area_id) or first, parent, source
            )
        )
    if len({area.id for area in areas}) != len(areas):
        raise ValueError(f"An area is in the pull twice: {list(ids)}")
    return areas


def shares_allowed(areas: Iterable[RankedArea]) -> bool:
    """True when a share of the total is true: every area is GADM, and no
    area contains another. GADM units at one level do not overlap and units
    in different branches are apart, so the sum is a real total. A GADM id
    contains the ids that start with it and a dot: BRA contains BRA.14, and
    BRA.1 does not contain BRA.14."""
    areas = list(areas)
    if any(area.source != NON_OVERLAPPING_SOURCE for area in areas):
        return False
    ids = {area.id for area in areas}
    for area_id in ids:
        parts = area_id.split(".")
        for end in range(1, len(parts)):
            if ".".join(parts[:end]) in ids:
                return False
    return True


def round_value(value: float) -> float:
    return round(value, VALUE_DECIMALS)


def build_ranking(
    rows: Iterable[dict],
    areas: Sequence[RankedArea],
    value_column: str,
) -> list[dict]:
    """The rows of a ranked bar chart, largest value first.

    Sums `value_column` per area over the rows. An area with no rows is 0.
    Rows are in rank order: value descending, then name. `rank` is a
    competition rank (1, 2, 3, 3, 5), so the areas with no value share the
    last rank. `share_pct` is on every row when `shares_allowed`, else on
    none.

    Returns [] when no value can be ranked: no row has the measure (the API
    sends a null for a measure it does not compute), or every total is 0.
    Raises ValueError when a row names an area that is not in `areas`, or
    when an area has rows but none with the measure while another area has
    it: that is not a pull to rank.
    """
    by_id = {area.id: area for area in areas}
    if len(by_id) != len(areas):
        raise ValueError("An area is in the pull twice")

    totals: dict[str, float] = {}
    areas_with_rows: set[str] = set()
    for row in rows:
        area_id = format_id(row.get("aoi_id"))
        if area_id not in by_id:
            raise ValueError(
                f"A pulled row is for an area that is not in the pull: "
                f"{row.get('aoi_id')!r}"
            )
        areas_with_rows.add(area_id)
        value = row.get(value_column)
        if value is not None:
            totals[area_id] = totals.get(area_id, 0.0) + float(value)

    if not totals:
        return []
    missing = areas_with_rows - set(totals)
    if missing:
        raise ValueError(
            f"No {value_column} in the rows of {sorted(missing)}, but other "
            "areas have it"
        )

    values = {area.id: round_value(totals.get(area.id, 0.0)) for area in areas}
    grand_total = sum(values.values())
    if grand_total <= 0:
        return []

    with_share = shares_allowed(areas)
    ordered = sorted(
        areas, key=lambda area: (-values[area.id], area.name, area.id)
    )
    ranked: list[dict] = []
    previous_value: Optional[float] = None
    rank = 0
    for position, area in enumerate(ordered, 1):
        value = values[area.id]
        if value != previous_value:
            rank = position
            previous_value = value
        row = {
            "rank": rank,
            "aoi_id": area.id,
            "name": area.name,
            "parent": area.parent,
            value_column: value,
        }
        if with_share:
            row["share_pct"] = round_value(value / grand_total * 100)
        ranked.append(row)
    return ranked
