"""Resolve a catalog dataset into a renderable map layer.

A dataset's ``tile_url`` in the catalog is a template: it may be relative to
the eoapi host, and it may carry a canopy-cover threshold, a year, or a date
range that only the caller knows. Turning it into a URL a map can render is
the same job whether the dataset was picked by the LLM in chat or named by an
API caller, so it lives here rather than inside the dataset-selection
subagent.

``pick_dataset`` adapts its own selection objects onto this function; the
dashboard recipes call it directly. One definition means a map widget built
by a recipe and one built from chat carry the same URL.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from src.agent.datasets.config import DATASETS
from src.agent.datasets.handlers.analytics_handler import (
    FOREST_CARBON_FLUX_ID,
    GRASSLANDS_ID,
    INTEGRATED_ALERTS_ID,
    LAND_COVER_CHANGE_ID,
    TREE_COVER_ID,
    TREE_COVER_LOSS_BY_DRIVER_ID,
    TREE_COVER_LOSS_BY_FIRES_ID,
    TREE_COVER_LOSS_ID,
)
from src.shared.config import SharedSettings

#: Datasets whose tiles are cut at a canopy-cover threshold.
_THRESHOLD_DATASETS = (
    TREE_COVER_LOSS_ID,
    TREE_COVER_ID,
    TREE_COVER_LOSS_BY_DRIVER_ID,
    TREE_COVER_LOSS_BY_FIRES_ID,
    FOREST_CARBON_FLUX_ID,
)
DEFAULT_CANOPY_COVER = 30

#: Tree cover loss tiles carry whole years, and only these are published.
TCL_TILE_YEARS = range(2001, 2026)


@dataclass(frozen=True)
class DatasetLayer:
    """One dataset rendered for one date range: what a map needs, nothing
    else. The prose fields of the catalog record stay out by design — this
    is what gets snapshotted into a dashboard widget."""

    dataset_id: int
    dataset_name: str
    tile_url: str
    start_date: str
    end_date: str
    context_layer: Optional[str] = None
    #: Companion layers to draw with the dataset, as
    #: ``{"name": ..., "tile_url": ...}``.
    context_layers: list[dict] = field(default_factory=list)
    #: The parameters the tile URL was built with, as
    #: ``{"name": ..., "values": [...]}``.
    parameters: Optional[list[dict]] = None


def get_dataset_record(dataset_id: int) -> dict:
    """The catalog record for a dataset id; raises ``ValueError`` if unknown."""
    record = next(
        (ds for ds in DATASETS if ds["dataset_id"] == dataset_id), None
    )
    if record is None:
        raise ValueError(f"Dataset not found: {dataset_id}")
    return record


def _canopy_cover(parameters: Optional[list[dict]]) -> int:
    for parameter in parameters or []:
        if parameter.get("name") == "canopy_cover" and parameter.get("values"):
            return max(parameter["values"])
    return DEFAULT_CANOPY_COVER


def resolve_dataset_layer(
    dataset_id: int,
    start_date: str,
    end_date: str,
    *,
    context_layer: Optional[str] = None,
    parameters: Optional[list[dict]] = None,
    record: Optional[dict] = None,
) -> DatasetLayer:
    """Build the renderable layer for a dataset over a date range.

    ``start_date`` / ``end_date`` are ISO dates the caller has already
    clamped to the dataset's coverage (``datasets.dates.revise_date_range``).
    ``context_layer`` names one of the dataset's context layers by its
    catalog ``value``; ``parameters`` are ``{"name", "values"}`` dicts, of
    which only ``canopy_cover`` currently changes a URL.

    ``record`` overrides the catalog lookup with the dataset row the caller
    already holds. ``pick_dataset`` passes its candidate row, whose context
    layers have been filtered to the ones that actually cover the selected
    area — resolving from the catalog instead would quietly undo that
    filter.
    """
    record = record if record is not None else get_dataset_record(dataset_id)
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)

    tile_url = record["tile_url"] or ""
    if tile_url and not tile_url.startswith("http"):
        tile_url = SharedSettings.eoapi_base_url + tile_url

    context_layers: list[dict] = []
    if context_layer and record.get("context_layers"):
        selected = next(
            (
                layer
                for layer in record["context_layers"]
                if layer.get("value") == context_layer
            ),
            None,
        )
        if selected:
            context_layers.append(
                {
                    "name": selected.get("value"),
                    "tile_url": selected.get("tile_url"),
                }
            )

    if dataset_id in _THRESHOLD_DATASETS:
        canopy_cover = _canopy_cover(parameters)
        if dataset_id != TREE_COVER_ID:
            canopy_tile_url = next(
                (
                    parameter["tile_url"]
                    for parameter in record.get("parameters") or []
                    if parameter["name"] == "canopy_cover"
                ),
                None,
            )
            if canopy_tile_url:
                context_layers.append(
                    {
                        "name": "canopy_cover",
                        "tile_url": canopy_tile_url.replace(
                            "{threshold}", str(canopy_cover)
                        ),
                    }
                )
        tile_url = tile_url.replace("{threshold}", str(canopy_cover))

    if dataset_id in (TREE_COVER_LOSS_ID, TREE_COVER_LOSS_BY_FIRES_ID):
        if end.year in TCL_TILE_YEARS:
            tile_url += f"&start_year={start.year}&end_year={end.year}"
        else:
            tile_url += (
                f"&start_year={TCL_TILE_YEARS.start}"
                f"&end_year={TCL_TILE_YEARS.stop - 1}"
            )
    elif dataset_id == INTEGRATED_ALERTS_ID:
        tile_url += f"&start_date={start_date}&end_date={end_date}"
    elif dataset_id in (LAND_COVER_CHANGE_ID, GRASSLANDS_ID):
        # Annual raster item in the URL; the dates are already clamped to the
        # dataset's own coverage.
        tile_url = tile_url.format(year=end.year)

    return DatasetLayer(
        dataset_id=dataset_id,
        dataset_name=record["dataset_name"],
        tile_url=tile_url,
        start_date=start_date,
        end_date=end_date,
        context_layer=context_layer,
        context_layers=context_layers,
        parameters=parameters,
    )
