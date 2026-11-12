import json
import time
from typing import Annotated, Any, Awaitable, Callable, Optional, Protocol

from langchain_core.messages import ToolMessage
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from src.agent.i18n import t
from src.agent.language import DEFAULT_LANGUAGE
from src.agent.tools.analytics_mcp.analysis_statistics import (
    analysis_statistics,
    analyzed_areas,
)
from src.agent.tools.analytics_mcp.area_names import names_seen
from src.agent.tools.analytics_mcp.area_selection import (
    UnsupportedAreaError,
    area_selection_entry,
)
from src.agent.tools.analytics_mcp.client import (
    AnalyticsMcp,
    AnalyticsMcpError,
)
from src.agent.tools.analytics_mcp.dataset_ids import (
    DatasetIds,
    UnknownDatasetError,
)
from src.agent.tools.analytics_mcp.payload_choices import PayloadChoices

FINISHED_STATUSES = ("saved", "success")


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


class AnalyticsMcpTools:
    """Zeno's area, dataset and data tools, answered by the analytics MCP
    server. Each records its outcome in the agent state, in the same shape as
    the tools of the same name that query Zeno's own sources."""

    def __init__(
        self,
        mcp: AnalyticsMcp,
        dataset_ids: DatasetIds,
        datasets: Datasets,
        payload_choices: PayloadChoices,
        record_statistics: Callable[[dict[str, Any]], Awaitable[str]],
        sleep: Callable[[float], Awaitable[None]],
        poll_timeout_seconds: float,
    ):
        self.mcp = mcp
        self.dataset_ids = dataset_ids
        self.datasets = datasets
        self.payload_choices = payload_choices
        self.record_statistics = record_statistics
        self.sleep = sleep
        self.poll_timeout_seconds = poll_timeout_seconds

    async def pick_aoi(
        self,
        places: list[str],
        state: Annotated[dict, InjectedState],
        tool_call_id: Annotated[str, InjectedToolCallId],
        area_types: Optional[list[str]] = None,
    ) -> Command:
        """Find areas by place name and select the best match for each, all
        in one selection: pass every place the question compares in one call.
        Give each place's full name, every word of it, with the country or
        region it is in after a comma (as in "Springfield, Illinois") and the
        kind of area in area_types rather than in the name.
        area_types can narrow the search to admin, key_biodiversity_area,
        protected_area or indigenous_land. Returns the selected areas with the
        aois to use in pull_data payloads, and other matches per place: if a
        best match is not the place meant, call again with a more specific
        name."""
        selected = []
        entries = []
        others = {}
        not_found = []
        for place in places:
            try:
                matches = await self.search(place, area_types)
                entry = area_selection_entry(matches[0]) if matches else None
            except (AnalyticsMcpError, UnsupportedAreaError) as error:
                return reply(str(error), tool_call_id)
            if entry is None:
                not_found.append(place)
                continue
            entries.append(entry)
            selected.append({"name": entry["name"], "aoi": matches[0]["aoi"]})
            others[place] = named_aois(matches[1:])
        if not entries:
            language = state.get("language") or DEFAULT_LANGUAGE
            return feedback(
                await t("pick_aoi.no_matching_aois", language), tool_call_id
            )
        result = {"selected": selected, "other_matches": others}
        if not_found:
            result["not_found"] = not_found
        content = json.dumps(result, ensure_ascii=False)
        name = ", ".join(entry["name"] for entry in entries)
        return Command(
            update={
                "aoi_selection": {"name": name, "aois": entries},
                "messages": [ToolMessage(content, tool_call_id=tool_call_id)],
            }
        )

    async def search(
        self, place: str, area_types: Optional[list[str]]
    ) -> list[dict[str, Any]]:
        arguments: dict[str, Any] = {"name": place, "limit": 5}
        if area_types:
            arguments["area_types"] = area_types
        return await self.mcp.call("search_areas", arguments)

    async def pick_dataset(
        self,
        dataset: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        intersections: Optional[list[str]] = None,
    ) -> Command:
        """Select a dataset by its name from list_datasets. intersections are
        the ones the analysis will request, such as ["driver"], since some
        intersections are datasets of their own. Returns the dataset's
        cautions and the payload schema pull_data accepts."""
        try:
            detail = await self.mcp.call(
                "describe_dataset", {"dataset": dataset}
            )
            dataset_id = self.dataset_ids.dataset_id_for(
                dataset, intersections
            )
        except (AnalyticsMcpError, UnknownDatasetError) as error:
            return reply(str(error), tool_call_id)
        selection = {
            **await self.datasets.selection(dataset_id),
            "analytics_dataset": dataset,
        }
        # The API's dataset card is left out: the catalog's cautions and
        # instructions already reach the model, and the card buries the
        # payload schema.
        content = json.dumps(
            {
                "name": detail["name"],
                "request_schema": detail["request_schema"],
                "cautions": selection.get("cautions"),
            },
            ensure_ascii=False,
        )
        return Command(
            update={
                "dataset": selection,
                "messages": [ToolMessage(content, tool_call_id=tool_call_id)],
            }
        )

    async def pull_data(
        self,
        dataset: str,
        payload: dict[str, Any],
        state: Annotated[dict, InjectedState],
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> Command:
        """Run an analysis of a dataset from list_datasets, with a payload
        matching the schema pick_dataset returned and the aoi pick_aoi
        returned. The results are kept for generate_insights."""
        try:
            dataset_id = self.dataset_ids.dataset_id_for(
                dataset, payload.get("intersections")
            )
            outcome = await self.finished_analysis(dataset, payload)
        except (AnalyticsMcpError, UnknownDatasetError) as error:
            return reply(str(error), tool_call_id)
        if outcome["status"] not in FINISHED_STATUSES:
            message = outcome.get("message") or outcome["status"]
            return reply(
                f"The analysis did not finish: {message}", tool_call_id
            )
        context_layer = self.payload_choices.context_layer(payload)
        selection = {
            **await self.datasets.selection(
                dataset_id,
                context_layer,
                self.payload_choices.canopy_cover(payload, context_layer),
            ),
            "analytics_dataset": dataset,
        }
        try:
            areas = analyzed_areas(
                payload["aoi"],
                state.get("aoi_selection") or {},
                names_seen(state.get("messages") or []),
            )
        except UnsupportedAreaError as error:
            return reply(str(error), tool_call_id)
        statistics = analysis_statistics(
            selection, payload, outcome["link"], areas
        )
        statistics["id"] = await self.record_statistics(statistics)
        rows = len(next(iter((outcome.get("result") or {}).values()), []))
        content = (
            f"Successfully pulled {statistics['dataset_name']} data for "
            f"{', '.join(statistics['aoi_names'])}. Found {rows} data points."
        )
        return Command(
            update={
                "aoi_selection": {
                    "name": ", ".join(area["name"] for area in areas),
                    "aois": areas,
                },
                "dataset": selection,
                "statistics": [statistics],
                "start_date": statistics["start_date"],
                "end_date": statistics["end_date"],
                "messages": [ToolMessage(content, tool_call_id=tool_call_id)],
            }
        )

    async def list_subregions(
        self,
        aoi: dict[str, Any],
        area_type: str = "admin",
        level: Optional[int] = None,
        limit: int = 50,
    ) -> str:
        """List the areas within an area, largest first, with how many there
        are in all, as aois for pull_data payloads. Use it for questions about
        the regions, states, counties or protected areas of a place, then pull
        them together in one payload. area_type is admin,
        key_biodiversity_area, protected_area or indigenous_land; for admin,
        level is the admin level to list (default: one below the area). The
        admin aoi WLD lists countries. When total is larger than the areas
        returned, ask for a higher level or a smaller area."""
        arguments = {
            "aoi": aoi,
            "area_type": area_type,
            "level": level,
            "limit": limit,
        }
        try:
            listed = await self.mcp.call("list_subregions", arguments)
        except AnalyticsMcpError as error:
            return str(error)
        return json.dumps(listed, ensure_ascii=False)

    async def list_datasets(self) -> str:
        """List the datasets that can be analyzed."""
        try:
            datasets = await self.mcp.call("list_datasets", {})
        except AnalyticsMcpError as error:
            return str(error)
        return json.dumps(datasets, ensure_ascii=False)

    async def finished_analysis(
        self, dataset: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Runs an analysis and checks on it until it finishes or the poll
        timeout passes."""
        outcome = await self.mcp.call(
            "run_analysis", {"dataset": dataset, "payload": payload}
        )
        deadline = time.monotonic() + self.poll_timeout_seconds
        while outcome["status"] == "pending" and time.monotonic() < deadline:
            await self.sleep(outcome.get("retry_after_seconds") or 1)
            outcome = await self.mcp.call(
                "get_analysis", {"link": outcome["link"]}
            )
        return outcome


def reply(content: str, tool_call_id: str) -> Command:
    """A result the model can act on, such as fixing its request."""
    return Command(
        update={"messages": [ToolMessage(content, tool_call_id=tool_call_id)]}
    )


def feedback(content: str, tool_call_id: str) -> Command:
    """A result the user sees and the turn stops on, as for Zeno's other
    tools."""
    message = ToolMessage(
        content,
        tool_call_id=tool_call_id,
        status="success",
        response_metadata={"msg_type": "human_feedback"},
    )
    return Command(update={"messages": [message]})


def named_aois(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Search matches as the names and aois shown to the model."""
    named = []
    for match in matches:
        named.append({"name": match["display_name"], "aoi": match["aoi"]})
    return named
