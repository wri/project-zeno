"""add_map_widget — put a map layer onto a dashboard as a widget.

The third dashboard primitive next to create_dashboard and add_to_dashboard.
A map widget snapshots the resolved layer already in agent state — either the
dataset layer picked by pick_dataset or the Sentinel-2 mosaic built by
show_imagery — into the widget's config, so the dashboard renders it without
any chat state. The dashboard defaults to the one in state or the one the
user is looking at (view_context). Owner-only, like the other primitives.

The snapshot projections live in ``src.api.services.widget_configs`` and
are shared with the analysis templates, so a layer added from chat and one
added by a template give the same config.
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
    resolve_section,
)
from src.api.repositories import dashboard_writer
from src.api.services.widget_configs import (
    dataset_config,
    imagery_config,
    widget_config,
)
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


def _dataset_summary(snapshot: dict) -> str:
    return (
        f"map widget for dataset '{snapshot['dataset_name']}' "
        f"({snapshot['start_date']}–{snapshot['end_date']})"
    )


def _imagery_summary(snapshot: dict) -> str:
    provider = snapshot.get("provider") or "Sentinel-2"
    return (
        f"{provider} imagery map widget (around "
        f"{snapshot['target_date']}, areas: "
        f"{', '.join(snapshot['aoi_names'] or [])})"
    )


class LayerHandler(NamedTuple):
    """How to build a map widget for one `layer` argument value: snapshot the
    relevant agent state, summarize it for the reply, or explain why neither
    is possible yet."""

    snapshot: Callable[[dict], Optional[dict]]
    summary: Callable[[dict], str]
    missing_message: str


LAYER_HANDLERS = {
    "dataset": LayerHandler(
        snapshot=dataset_config,
        summary=_dataset_summary,
        missing_message=(
            "No dataset layer selected. Run pick_dataset first, then add "
            "the layer to the dashboard."
        ),
    ),
    "imagery": LayerHandler(
        snapshot=imagery_config,
        summary=_imagery_summary,
        missing_message=(
            "No imagery built this conversation. Run show_imagery first, "
            "then add it to the dashboard."
        ),
    ),
}


@tool("add_map_widget")
async def add_map_widget(
    layer: str,
    dashboard_id: Optional[str] = None,
    title: Optional[str] = None,
    section: Optional[str] = None,
    state: Annotated[Dict, InjectedState] | None = None,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Add a map widget to a dashboard.

    `layer="dataset"` snapshots the currently selected dataset layer
    (pick_dataset must have run); `layer="imagery"` snapshots the Sentinel-2
    mosaic from show_imagery. `dashboard_id` defaults to the dashboard in
    state or the one the user is currently viewing; `title` optionally
    overrides the widget header; `section` places the widget in one of the
    dashboard's sections (by title or id), otherwise it lands ungrouped at
    the top level. The widget renders focused on the dashboard's area. Only
    dashboards the user owns can be edited.
    """
    state = state or {}

    layer_type = LAYER_HANDLERS.get(layer)
    if layer_type is None:
        return error_command(
            "layer must be 'dataset' or 'imagery'.", tool_call_id
        )

    snapshot = layer_type.snapshot(state)
    if snapshot is None:
        return error_command(layer_type.missing_message, tool_call_id)

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

    dashboard = await load_editable_dashboard(
        target_dashboard, "add_map_widget"
    )
    if dashboard is None:
        return error_command(
            f"Dashboard {target_dashboard} not found or not editable.",
            tool_call_id,
        )

    target_section, message = resolve_section(dashboard, section)
    if message:
        return error_command(message, tool_call_id)

    widget_id = await dashboard_writer.add_widget(
        str(target_dashboard),
        widget_type="map",
        config=widget_config(layer, snapshot, title),
        section_id=str(target_section.id) if target_section else None,
    )
    if widget_id is None:
        return error_command(
            f"Dashboard {target_dashboard} disappeared before the map "
            "widget could be added.",
            tool_call_id,
        )

    return dashboard_updated_command(
        dashboard.id,
        dashboard.name,
        (
            f"Added {layer_type.summary(snapshot)} to dashboard "
            f"'{dashboard.name}' ({dashboard.id})"
            + (
                f" in section '{target_section.title}'"
                if target_section
                else ""
            )
            + "."
        ),
        tool_call_id,
    )


SPEC = ToolSpec(
    tool=add_map_widget,
    category=ToolCategory.PRIMITIVE,
    prompt_fragment=(
        "- add_map_widget(layer, dashboard_id?, title?, section?): add a map "
        "widget to "
        "a dashboard. layer='dataset' snapshots the currently selected "
        "dataset layer (pick_dataset must have run); layer='imagery' "
        "snapshots the Sentinel-2 mosaic from show_imagery. Dashboard "
        "defaults to the one in state or on screen; `section` (a section "
        "title or id) groups it. Use when the user asks "
        "to add a layer, map or satellite imagery to their dashboard."
    ),
)
