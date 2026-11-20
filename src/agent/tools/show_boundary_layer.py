"""show_boundary_layer — put a concessions boundary layer on the map.

Concessions are not searchable by name, so the way to reach one concession
is to show its layer and let the user click it. This tool only writes the
layer to ``state["boundary_layer"]``; the frontend switches its boundary
layer to it, and a click on a feature picks that concession as the AOI.

Showing a layer is not an area selection: the AOI in state is unchanged.
With no layer type the tool offers the types as a nudge instead.
"""

from typing import Annotated, Literal, Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.types import Command

from src.agent.tool_spec import ToolCategory, ToolSpec
from src.agent.tools.send_nudge import NUDGE_ALREADY_SET_NOTE

BoundaryLayerType = Literal[
    "oil_palm", "rspo_oil_palm", "logging", "mining", "wood_fiber"
]

# The layer titles, in the order the nudge offers them. The keys are the
# backend source keys (CONCESSION_SOURCES); the frontend upper-cases them to
# its boundary layer ids (OIL_PALM, ...).
BOUNDARY_LAYERS: dict[str, str] = {
    "oil_palm": "Oil palm concessions",
    "rspo_oil_palm": "RSPO oil palm concessions",
    "logging": "Logging concessions",
    "mining": "Mining concessions",
    "wood_fiber": "Wood fiber concessions",
}

BOUNDARY_LAYER_NUDGE = "boundary_layer_choice"


def _message(content: str, tool_call_id: Optional[str]) -> ToolMessage:
    return ToolMessage(
        content,
        tool_call_id=tool_call_id,
        status="success",
        response_metadata={"msg_type": "human_feedback"},
    )


@tool("show_boundary_layer")
async def show_boundary_layer(
    layer: Optional[BoundaryLayerType] = None,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Show a concessions boundary layer on the map, so the user can click a
    concession to select it.

    layer is the concession type: oil_palm, rspo_oil_palm (only when the
    user says RSPO), logging, mining or wood_fiber. Pass null when the user
    gives no type; the tool then offers the types to the user.
    """
    if layer is None:
        options = list(BOUNDARY_LAYERS.values())
        return Command(
            update={
                "nudge": {"type": BOUNDARY_LAYER_NUDGE, "options": options},
                "messages": [
                    _message(
                        "The user did not say which type of concessions. "
                        "Ask which type to show, and list the available "
                        "types: "
                        + "; ".join(options)
                        + "."
                        + NUDGE_ALREADY_SET_NOTE,
                        tool_call_id,
                    )
                ],
            }
        )

    name = BOUNDARY_LAYERS[layer]
    return Command(
        update={
            "boundary_layer": {"source": layer, "name": name},
            "messages": [
                _message(
                    f"The {name} boundary layer is now on the map. Tell the "
                    "user to click a concession on the map to select it and "
                    "analyse it. No concession is selected yet, so do not "
                    "give figures for concessions.",
                    tool_call_id,
                )
            ],
        }
    )


SPEC = ToolSpec(
    tool=show_boundary_layer,
    category=ToolCategory.PRIMITIVE,
    prompt_fragment=(
        "- show_boundary_layer(layer): show a concessions boundary layer "
        "(oil_palm, rspo_oil_palm, logging, mining, wood_fiber) on the map "
        "so the user can click a concession. With layer=null it offers the "
        "types to the user."
    ),
)
