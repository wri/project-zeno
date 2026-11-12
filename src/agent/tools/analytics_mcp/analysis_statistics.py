from datetime import date
from typing import Any

from src.agent.tools.analytics_mcp.area_selection import area_selection_entry
from src.shared.geocoding_helpers import format_id


def analysis_statistics(
    dataset: dict[str, Any],
    payload: dict[str, Any],
    link: str,
    areas: list[dict[str, Any]],
) -> dict[str, Any]:
    """A finished analysis of these areas as a statistics entry, in the shape
    the insight generator and evaluations read. Its data is fetched from the
    analysis link when needed, as for other statistics."""
    start_date, end_date = requested_dates(payload, dataset)
    return {
        "dataset_name": dataset["dataset_name"],
        "dataset_id": dataset["dataset_id"],
        "start_date": start_date,
        "end_date": end_date,
        "source_url": link,
        "data": {},
        "aoi_id_to_name": {
            format_id(area["src_id"]): area["name"] for area in areas
        },
        "aoi_names": [area["name"] for area in areas],
        "aoi_ids": [area["src_id"] for area in areas],
        "aoi_sources": [area["source"] for area in areas],
        "parameters": dataset.get("parameters"),
        "context_layer": dataset.get("context_layer"),
    }


def analyzed_areas(
    aoi: dict[str, Any],
    aoi_selection: dict[str, Any],
    names: dict[str, str],
) -> list[dict[str, Any]]:
    """The areas an analysis covered, as AOI selection entries: as selected
    when the selection holds them, otherwise named from `names` or by id."""
    selected = {
        format_id(area["src_id"]): area
        for area in aoi_selection.get("aois", [])
    }
    areas = []
    for aoi_id in aoi["ids"]:
        if aoi_id in selected:
            areas.append(selected[aoi_id])
            continue
        match = {
            "display_name": names.get(aoi_id, aoi_id),
            "aoi": {**aoi, "ids": [aoi_id]},
        }
        areas.append(area_selection_entry(match))
    return areas


def requested_dates(
    payload: dict[str, Any], dataset: dict[str, Any]
) -> tuple[str, str]:
    """The period a payload asked for, as dates. Payloads without one cover
    the dataset's whole period."""
    if "start_year" in payload:
        start_date = f"{payload['start_year']}-01-01"
    else:
        start_date = payload.get("start_date") or dataset["start_date"]
    if "end_year" in payload:
        end_date = f"{payload['end_year']}-12-31"
    else:
        end_date = (
            payload.get("end_date")
            or dataset.get("end_date")
            or str(date.today())
        )
    return start_date, end_date
