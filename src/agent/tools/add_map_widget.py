"""add_map_widget — put a map layer onto a dashboard as a widget.

The third dashboard primitive next to create_dashboard and add_to_dashboard.
A map widget snapshots the resolved layer already in agent state — either the
dataset layer picked by pick_dataset or the Sentinel-2 mosaic built by
show_imagery — into the widget's config, so the dashboard renders it without
any chat state. The dashboard defaults to the one in state or the one the
user is looking at (view_context). Owner-only, like the other primitives.

The snapshot is an explicit key allowlist: only render-relevant fields are
copied, so the prose fields on the dataset state (description, methodology,
instructions, ...) can never leak into the database.
"""

from typing import Annotated, Callable, Dict, NamedTuple, Optional

from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from src.agent.tool_spec import ToolCategory, ToolSpec
from src.agent.tools.common import (
    dashboard_updated_command,
    error_command,
    load_editable_dashboard,
    resolve_dashboard_id,
)
from src.api.repositories import dashboard_writer
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

# Render-relevant fields of the imagery state (ImageryState) — all of it.
_IMAGERY_KEYS = (
    "tile_url",
    "tilejson_url",
    "mosaic_id",
    "item_count",
    "date_start",
    "date_end",
    "target_date",
    "window_days",
    "max_cloud_cover",
    "aoi_names",
)


def _dataset_config(state: dict) -> Optional[dict]:
    """Project the dataset in state onto the widget-config snapshot.

    Returns None when no dataset is selected or it carries no tile URL
    (nothing to render). Dates fall back to the top-level effective range
    set by pull_data.
    """
    dataset = state.get("dataset") or {}
    if not dataset.get("tile_url"):
        return None
    parameters = dataset.get("parameters")
    return {
        "dataset_id": dataset.get("dataset_id"),
        "dataset_name": dataset.get("dataset_name"),
        "tile_url": dataset["tile_url"],
        "context_layer": dataset.get("context_layer"),
        "context_layers": dataset.get("context_layers"),
        "parameters": [
            {"name": p.get("name"), "values": p.get("values")}
            for p in parameters
        ]
        if parameters
        else None,
        "start_date": dataset.get("start_date") or state.get("start_date"),
        "end_date": dataset.get("end_date") or state.get("end_date"),
    }


def _imagery_config(state: dict) -> Optional[dict]:
    """Snapshot the imagery in state (ImageryState shape) for the widget.

    Returns None when no imagery was built this conversation or the state
    lacks a tile URL / mosaic id to render from.
    """
    imagery = state.get("imagery") or {}
    if not imagery.get("tile_url") or not imagery.get("mosaic_id"):
        return None
    return {key: imagery.get(key) for key in _IMAGERY_KEYS}


def _dataset_summary(snapshot: dict) -> str:
    return (
        f"map widget for dataset '{snapshot['dataset_name']}' "
        f"({snapshot['start_date']}–{snapshot['end_date']})"
    )


def _imagery_summary(snapshot: dict) -> str:
    return (
        f"Sentinel-2 imagery map widget (around "
        f"{snapshot['target_date']}, areas: "
        f"{', '.join(snapshot['aoi_names'] or [])})"
    )


class _LayerKind(NamedTuple):
    """Everything layer-specific about a map widget, in one row."""

    snapshot: Callable[[dict], Optional[dict]]
    summary: Callable[[dict], str]
    missing_message: str


_LAYER_KINDS = {
    "dataset": _LayerKind(
        snapshot=_dataset_config,
        summary=_dataset_summary,
        missing_message=(
            "No dataset layer selected. Run pick_dataset first, then add "
            "the layer to the dashboard."
        ),
    ),
    "imagery": _LayerKind(
        snapshot=_imagery_config,
        summary=_imagery_summary,
        missing_message=(
            "No imagery built this conversation. Run show_imagery first, "
            "then add it to the dashboard."
        ),
    ),
}


def _widget_config(layer: str, snapshot: dict, title: Optional[str]) -> dict:
    config: dict = {"default_view": "map", layer: snapshot}
    if title:
        config["title"] = title
    return config


@tool("add_map_widget")
async def add_map_widget(
    layer: str,
    dashboard_id: Optional[str] = None,
    title: Optional[str] = None,
    state: Annotated[Dict, InjectedState] | None = None,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Add a map widget to a dashboard.

    `layer="dataset"` snapshots the currently selected dataset layer
    (pick_dataset must have run); `layer="imagery"` snapshots the Sentinel-2
    mosaic from show_imagery. `dashboard_id` defaults to the dashboard in
    state or the one the user is currently viewing; `title` optionally
    overrides the widget header. The widget renders focused on the
    dashboard's area. Only dashboards the user owns can be edited.
    """
    state = state or {}

    kind = _LAYER_KINDS.get(layer)
    if kind is None:
        return error_command(
            "layer must be 'dataset' or 'imagery'.", tool_call_id
        )

    snapshot = kind.snapshot(state)
    if snapshot is None:
        return error_command(kind.missing_message, tool_call_id)

    target_dashboard = resolve_dashboard_id(state, dashboard_id)
    if not target_dashboard:
        return error_command(
            "No dashboard to add to. Create one with create_dashboard, or "
            "pass a dashboard_id.",
            tool_call_id,
        )

    logger.info(
        "add_map_widget tool called",
        layer=layer,
        dashboard_id=str(target_dashboard),
    )

    dashboard = await load_editable_dashboard(target_dashboard)
    if dashboard is None:
        return error_command(
            f"Dashboard {target_dashboard} not found or not editable.",
            tool_call_id,
        )

    widget_id = await dashboard_writer.add_widget(
        str(target_dashboard),
        widget_type="map",
        config=_widget_config(layer, snapshot, title),
    )
    if widget_id is None:
        return error_command(
            f"Dashboard {target_dashboard} disappeared before the map "
            "widget could be added.",
            tool_call_id,
        )

    return dashboard_updated_command(
        dashboard.id,
        (
            f"Added {kind.summary(snapshot)} to dashboard "
            f"'{dashboard.name}' ({dashboard.id})."
        ),
        tool_call_id,
    )


SPEC = ToolSpec(
    tool=add_map_widget,
    category=ToolCategory.PRIMITIVE,
    prompt_fragment=(
        "- add_map_widget(layer, dashboard_id?, title?): add a map widget to "
        "a dashboard. layer='dataset' snapshots the currently selected "
        "dataset layer (pick_dataset must have run); layer='imagery' "
        "snapshots the Sentinel-2 mosaic from show_imagery. Dashboard "
        "defaults to the one in state or on screen. Use when the user asks "
        "to add a layer, map or satellite imagery to their dashboard."
    ),
)
