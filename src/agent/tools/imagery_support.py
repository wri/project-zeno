"""Shared plumbing for the imagery tools.

Both imagery tools resolve the same AOI/date inputs and emit the same kind of
Command; only the provider they reach for differs. Keeping that here lets each
tool stay a thin adapter over the provider classes.
"""

from datetime import date
from typing import Optional, Union

from langchain_core.messages import ToolMessage
from langgraph.types import Command

from src.agent.i18n import t
from src.agent.imagery import ImageryProviderResult, ImageryRequest
from src.agent.language import DEFAULT_LANGUAGE


def feedback(message: str, tool_call_id: Optional[str]) -> Command:
    """A message for the user that carries no imagery layer."""
    return Command(
        update={
            "messages": [
                ToolMessage(
                    message,
                    tool_call_id=tool_call_id,
                    status="success",
                    response_metadata={"msg_type": "human_feedback"},
                )
            ],
        },
    )


def provider_command(
    result: ImageryProviderResult, tool_call_id: Optional[str]
) -> Command:
    message = ToolMessage(
        result.message,
        tool_call_id=tool_call_id,
        status="success",
        response_metadata={"msg_type": "human_feedback"}
        if result.status == "error"
        else {},
    )
    update = {"messages": [message]}
    if result.imagery is not None:
        update["imagery"] = result.imagery.model_dump()
    return Command(update=update)


async def build_request(
    state: Optional[dict],
    target_date: Optional[str],
    tool_call_id: Optional[str],
    window_days: Optional[int] = None,
    max_cloud_cover: Optional[int] = None,
) -> Union[ImageryRequest, Command]:
    """The request for this call, or a Command explaining why there isn't one.

    Returning the failure as a Command keeps both tools' happy paths flat.
    """
    language = (state or {}).get("language") or DEFAULT_LANGUAGE
    aois = ((state or {}).get("aoi_selection") or {}).get("aois") or []
    if not aois:
        return feedback(await t("show_imagery.no_aoi", language), tool_call_id)

    parsed_date = None
    if target_date:
        try:
            parsed_date = date.fromisoformat(target_date)
        except ValueError:
            return feedback(
                await t(
                    "show_imagery.invalid_date",
                    language,
                    target_date=target_date,
                ),
                tool_call_id,
            )

    return ImageryRequest(
        aois=aois,
        target_date=parsed_date,
        language=language,
        window_days=window_days,
        max_cloud_cover=max_cloud_cover,
    )
