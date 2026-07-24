"""send_nudge — offer the user a set of clickable options.

A generic, stateless signal: no DB access, no InjectedState read, just an
update to `state["nudge"]` plus a ToolMessage tagged `msg_type:
human_feedback` so the turn is understood to end waiting on the user (the
same convention pick_dataset, pick_aoi, pull_data, show_imagery and the
analyst already use). Resolution needs no dedicated mechanism: the frontend
renders `options` as buttons, and a click resubmits the chosen string as the
user's next message — exactly how follow_up_suggestions already behaves.
"""

from typing import Annotated, Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.types import Command

from src.agent.tool_spec import ToolCategory, ToolSpec


@tool("send_nudge")
async def send_nudge(
    nudge_type: str,
    options: list[str],
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Offer the user a small set of clickable options instead of an
    open-ended question.

    `nudge_type` is a free-form label for the kind of choice being offered
    (e.g. "confirm", "clarify") — it's for the frontend to key rendering on,
    not validated against a fixed list. `options` are the exact strings
    shown as buttons; clicking one resubmits it as the user's next message,
    so keep them short and unambiguous on their own.
    """
    return Command(
        update={
            "nudge": {"type": nudge_type, "options": options},
            "messages": [
                ToolMessage(
                    content="Offered the user: " + "; ".join(options),
                    tool_call_id=tool_call_id,
                    status="success",
                    response_metadata={"msg_type": "human_feedback"},
                )
            ],
        }
    )


SPEC = ToolSpec(
    tool=send_nudge,
    category=ToolCategory.PRIMITIVE,
    prompt_fragment=(
        "- send_nudge(nudge_type, options): offer the user 2-4 clickable "
        "choices instead of asking an open-ended question. `nudge_type` is "
        "a free-form label for the kind of choice (e.g. 'confirm', "
        "'clarify'); `options` are the exact strings shown as buttons — "
        "clicking one resubmits it as the user's next message."
    ),
)
