from typing import Any, Optional

import pandas as pd

from src.agent.datasets.dates import revise_date_range
from src.agent.subagents.pick_dataset.schema import (
    DatasetOption,
    DatasetParameter,
    DatasetSelectionResult,
)
from src.agent.subagents.pick_dataset.tool import get_tile_services_for_dataset

TEXT_FIELDS = (
    "analytics_api_endpoint",
    "description",
    "prompt_instructions",
    "methodology",
    "cautions",
    "function_usage_notes",
    "citation",
    "content_date",
)
OPTIONAL_FIELDS = (
    "selection_hints",
    "code_instructions",
    "presentation_instructions",
)


class CatalogDatasets:
    """Catalog datasets in the shape pick_dataset selects them, with the map
    layers for the dataset's whole period and no context layer."""

    def __init__(self, catalog: list[dict[str, Any]]):
        self.rows = {row["dataset_id"]: row for row in catalog}

    async def selection(
        self,
        dataset_id: int,
        context_layer: Optional[str] = None,
        canopy_cover: Optional[int] = None,
    ) -> dict[str, Any]:
        row = self.rows[dataset_id]
        start_date, end_date, _ = await revise_date_range(
            None, None, dataset_id, context_layer
        )
        option = DatasetOption(
            dataset_id=dataset_id,
            context_layer=context_layer,
            parameters=canopy_cover_parameters(row, canopy_cover),
            reason="",
        )
        tile_url, context_layers, layers = get_tile_services_for_dataset(
            option, pd.Series(row), start_date, end_date
        )
        texts = {field: row.get(field) or "" for field in TEXT_FIELDS}
        optional = {field: row.get(field) for field in OPTIONAL_FIELDS}
        return DatasetSelectionResult(
            **option.model_dump(exclude={"start_date", "end_date"}),
            **texts,
            **optional,
            dataset_name=row["dataset_name"],
            start_date=start_date,
            end_date=end_date,
            tile_url=tile_url,
            layers=layers,
            context_layers=context_layers,
        ).model_dump()


def canopy_cover_parameters(
    row: dict[str, Any], canopy_cover: Optional[int]
) -> Optional[list[DatasetParameter]]:
    """The canopy cover chosen for a dataset, as its catalog parameter."""
    if canopy_cover is None:
        return None
    for parameter in row.get("parameters") or []:
        if parameter["name"] == "canopy_cover":
            return [
                DatasetParameter(
                    name="canopy_cover",
                    description=parameter.get("description", ""),
                    values=[canopy_cover],
                )
            ]
    return None
