"""The agent state each analytics MCP tool records, in the same shape as the
tools of the same name that query Zeno's own sources."""

from typing import Any, Awaitable, Callable, Optional, Protocol

from src.agent.tools.analytics_mcp.state_adapters.aoi_selection import (
    analyzed_areas,
    area_selection_entry,
    names_seen,
)
from src.agent.tools.analytics_mcp.state_adapters.catalog_ids import (
    DatasetIds,
)
from src.agent.tools.analytics_mcp.state_adapters.payload_choices import (
    PayloadChoices,
)
from src.agent.tools.analytics_mcp.state_adapters.statistics import (
    analysis_statistics,
)


class Datasets(Protocol):
    async def selection(
        self,
        dataset_id: int,
        context_layer: Optional[str] = None,
        canopy_cover: Optional[int] = None,
    ) -> dict[str, Any]:
        """The catalog dataset, in the shape of a dataset selection with the
        given context layer and canopy cover."""
        ...


class StateUpdates:
    def __init__(
        self,
        dataset_ids: DatasetIds,
        datasets: Datasets,
        payload_choices: PayloadChoices,
        record_statistics: Callable[[dict[str, Any]], Awaitable[str]],
    ):
        self.dataset_ids = dataset_ids
        self.datasets = datasets
        self.payload_choices = payload_choices
        self.record_statistics = record_statistics

    def catalog_dataset_id(
        self, dataset: str, intersections: Optional[list[str]]
    ) -> int:
        """The catalog dataset for an analytics API dataset, raising
        UnknownDatasetError when there is none."""
        return self.dataset_ids.dataset_id_for(dataset, intersections)

    def areas_picked(self, matches: list[dict[str, Any]]) -> dict[str, Any]:
        """The AOI selection of the best match for each place."""
        entries = [area_selection_entry(match) for match in matches]
        name = ", ".join(entry["name"] for entry in entries)
        return {"aoi_selection": {"name": name, "aois": entries}}

    async def dataset_picked(
        self, dataset: str, dataset_id: int
    ) -> dict[str, Any]:
        """The dataset selection, named as the analytics API names it."""
        selection = await self.datasets.selection(dataset_id)
        return {"dataset": {**selection, "analytics_dataset": dataset}}

    async def analysis_finished(
        self,
        dataset: str,
        dataset_id: int,
        payload: dict[str, Any],
        outcome: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        """The areas, dataset choices, statistics and period of a finished
        analysis. The choices are read from the request that ran, which
        datasets wrapping another fill in, such as a forest filter. Raises
        UnsupportedAreaError for areas Zeno can't select."""
        ran = outcome.get("metadata") or payload
        context_layer = self.payload_choices.context_layer(ran)
        selection = {
            **await self.datasets.selection(
                dataset_id,
                context_layer,
                self.payload_choices.canopy_cover(ran, context_layer),
            ),
            "analytics_dataset": dataset,
        }
        areas = analyzed_areas(
            payload["aoi"],
            state.get("aoi_selection") or {},
            names_seen(state.get("messages") or []),
        )
        statistics = analysis_statistics(
            selection, payload, outcome["link"], areas
        )
        statistics["id"] = await self.record_statistics(statistics)
        return {
            "aoi_selection": {
                "name": ", ".join(area["name"] for area in areas),
                "aois": areas,
            },
            "dataset": selection,
            "statistics": [statistics],
            "start_date": statistics["start_date"],
            "end_date": statistics["end_date"],
        }
