"""Map tile layers for a dataset over a date range."""

from datetime import datetime
from types import SimpleNamespace
from typing import Optional

import pandas as pd
from pydantic import BaseModel

from src.agent.datasets.config import DATASETS
from src.agent.datasets.handlers.analytics_handler import (
    DEFAULT_CANOPY_COVER,
    FOREST_CARBON_FLUX_ID,
    GRASSLANDS_ID,
    INTEGRATED_ALERTS_ID,
    LAND_COVER_CHANGE_ID,
    NATURAL_FOREST_DEFAULT_CANOPY_COVER,
    TREE_COVER_ID,
    TREE_COVER_LOSS_BY_DRIVER_ID,
    TREE_COVER_LOSS_BY_FIRES_ID,
    TREE_COVER_LOSS_ID,
)
from src.shared.config import SharedSettings


class ContextLayer(BaseModel):
    name: str
    tile_url: Optional[str]


class DatasetLayer(BaseModel):
    """A dataset's primary, independently-toggleable data layer. Distinct from
    ContextLayer, which is a mutually-exclusive masking/reference overlay —
    sibling DatasetLayers can all be shown at once (e.g. LGMS's "agriculture"
    and "lulucf" layers)."""

    name: str
    tile_url: str
    # Human label and plain-language meaning (including what the layer
    # measures, e.g. net flux vs gross emissions). `name` stays the machine id.
    title: Optional[str] = None
    description: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


def get_tile_services_for_dataset(
    selection_result, selected_row, start_date, end_date
):
    context_layers = []
    # Deprecated top-level tile_url mirror — left as the yml's own field,
    # unresolved against `selected_layer`/`layers`. Readers of the live
    # response check `layers` themselves for a multi-layer dataset (e.g.
    # pickDataset.ts); add_map_widget.py resolves selected_layer/layers[0]
    # on its own at persistence time, where a single tile_url is actually
    # required — no need to duplicate that here.
    tile_url = selected_row.tile_url
    start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_date = datetime.strptime(end_date, "%Y-%m-%d").date()

    if tile_url and not tile_url.startswith("http"):
        tile_url = SharedSettings.eoapi_base_url + tile_url

    if (
        selection_result.context_layer
        and selected_row.context_layers is not None
    ):
        selected_context_layer = next(
            (
                x
                for x in selected_row.context_layers
                if x["value"] == selection_result.context_layer
            ),
            None,
        )
        context_tile_url = selected_context_layer.get("tile_url")
        if context_tile_url and not context_tile_url.startswith("http"):
            context_tile_url = SharedSettings.eoapi_base_url + context_tile_url
        context_layer = ContextLayer(
            name=selected_context_layer.get("value"),
            tile_url=context_tile_url,
        )
        context_layers.append(context_layer)

    if selected_row.dataset_id in [
        TREE_COVER_LOSS_ID,
        TREE_COVER_ID,
        TREE_COVER_LOSS_BY_DRIVER_ID,
        TREE_COVER_LOSS_BY_FIRES_ID,
        FOREST_CARBON_FLUX_ID,
    ]:
        natural_forest = selection_result.context_layer == "natural_forest"
        canopy_cover = (
            NATURAL_FOREST_DEFAULT_CANOPY_COVER
            if natural_forest
            else DEFAULT_CANOPY_COVER
        )
        if selection_result.parameters is not None:
            for param in selection_result.parameters:
                if param.name == "canopy_cover":
                    canopy_cover = max(param.values)

        if selected_row.dataset_id != TREE_COVER_ID and not natural_forest:
            canopy_cover_tile_url = next(
                (
                    param["tile_url"]
                    for param in selected_row.parameters
                    if param["name"] == "canopy_cover"
                ),
                None,
            )

            thresholded_tile_url = canopy_cover_tile_url.replace(
                "{threshold}", str(canopy_cover)
            )

            context_layer = ContextLayer(
                name="canopy_cover",
                tile_url=thresholded_tile_url,
            )
            context_layers.append(context_layer)

        tile_url = tile_url.replace("{threshold}", str(canopy_cover))

    if (
        selected_row.dataset_id == TREE_COVER_LOSS_ID
        or selected_row.dataset_id == TREE_COVER_LOSS_BY_FIRES_ID
    ):
        if end_date.year in range(2001, 2026):
            tile_url += (
                f"&start_year={start_date.year}&end_year={end_date.year}"
            )
        else:
            tile_url += "&start_year=2001&end_year=2025"
    elif selection_result.dataset_id == INTEGRATED_ALERTS_ID:
        tile_url += f"&start_date={start_date}&end_date={end_date}"
    elif selection_result.dataset_id in [LAND_COVER_CHANGE_ID, GRASSLANDS_ID]:
        # Annual raster item in URL; start/end are already clamped to dataset YAML
        tile_url = tile_url.format(year=end_date.year)

    layers = get_dataset_layers(selected_row, tile_url)

    return tile_url, context_layers, layers


def with_date_range(dataset: dict, start_date: str, end_date: str) -> dict:
    """The dataset with its dates and map tiles moved to another range."""
    selection = SimpleNamespace(
        dataset_id=dataset["dataset_id"],
        context_layer=dataset.get("context_layer"),
        parameters=[
            SimpleNamespace(**param)
            for param in dataset.get("parameters") or []
        ],
    )
    record = pd.Series(
        next(
            ds for ds in DATASETS if ds["dataset_id"] == dataset["dataset_id"]
        )
    )
    tile_url, context_layers, layers = get_tile_services_for_dataset(
        selection, record, start_date, end_date
    )
    return {
        **dataset,
        "start_date": start_date,
        "end_date": end_date,
        "tile_url": tile_url,
        "layers": [layer.model_dump() for layer in layers],
        "context_layers": [layer.model_dump() for layer in context_layers],
    }


def to_dataset_layers(raw_layers: list[dict]) -> list[DatasetLayer]:
    """Catalog yml `layers` entries as DatasetLayers."""
    return [
        DatasetLayer(
            name=layer["name"],
            tile_url=layer["tile_url"],
            title=layer.get("title"),
            description=layer.get("description"),
            start_date=layer.get("start_date"),
            end_date=layer.get("end_date"),
        )
        for layer in raw_layers
    ]


def get_dataset_layers(selected_row, tile_url: str) -> list[DatasetLayer]:
    """The dataset's primary layer(s): the yml's explicit `layers` list when
    present (e.g. LGMS's agriculture/lulucf), otherwise a single layer
    auto-derived from the dataset's resolved `tile_url` — so every other
    catalog entry keeps working unchanged with no per-dataset branching
    downstream. Empty for an analytics-only dataset with no tile_url and no
    `layers` — there's nothing to render, so no placeholder entry is worth
    manufacturing."""
    raw_layers = getattr(selected_row, "layers", None)
    if isinstance(raw_layers, list) and raw_layers:
        return to_dataset_layers(raw_layers)
    if not tile_url:
        return []
    return [DatasetLayer(name=selected_row.dataset_name, tile_url=tile_url)]
