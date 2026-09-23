"""Per-turn Langfuse trace attributes for /api/chat.

Pure functions (no IO) so the tracing contract is unit-testable without a
graph, a checkpointer or Langfuse. ``stream_chat`` feeds them the parsed
request and the thread state it already reads each turn.
"""

from dataclasses import dataclass
from typing import Any, Optional

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

# Trace name for every chat turn (was LangGraph's default "LangGraph"). The
# Langfuse CallbackHandler names the trace after the root run, which takes
# config["run_name"].
CHAT_TURN_RUN_NAME = "chat_turn"


@dataclass(frozen=True)
class NudgeMatch:
    matched: bool
    type: Optional[str] = None
    option_index: Optional[int] = None


NO_MATCH = NudgeMatch(matched=False)


def match_pending_nudge(
    nudge: Any, query: str, thread_id: Optional[str] = None
) -> NudgeMatch:
    """Does ``query`` equal an option of the thread's pending nudge?

    A server-side cross-check on the client's ``input_source``: it catches
    clicks from clients that do not send the field, and ``input_source``
    "typed" with a match flags frontend mislabelling. It never overrides
    what the client said.

    Matching is exact after stripping surrounding whitespace, and case
    sensitive. The frontend resubmits the option string verbatim, so a
    click always matches exactly; casefolding would count a typed "yes"
    against a "Yes" option as a click, which is the distinction this
    exists to measure. No Unicode normalisation either: the option
    round-trips through JSON unchanged.

    Known false positives and negatives, accepted: ``state.nudge`` is
    last-write-wins and never reset per turn (pick_aoi does not clear an
    aoi_choice; send_nudge nudges persist until overwritten), so "pending"
    means "the nudge currently in state", which can be several turns old.
    Typing the exact text of a stale option counts as a match, and clicking
    an older nudge button still shown in the chat history does not.

    A malformed nudge (older state shapes on long-lived threads) is logged
    and treated as no match rather than raised: this is an analytics
    signal and must not break the chat turn.
    """
    if not nudge:
        return NO_MATCH
    if not isinstance(nudge, dict):
        logger.warning(
            "Malformed pending nudge, skipping nudge match",
            thread_id=thread_id,
            nudge_kind=type(nudge).__name__,
        )
        return NO_MATCH
    nudge_type = nudge.get("type")
    options = nudge.get("options")
    if not nudge_type and not options:
        # Cleared nudge (pick_dataset writes {"type": "", "options": []}).
        return NO_MATCH
    if not isinstance(nudge_type, str) or not isinstance(options, list):
        logger.warning(
            "Malformed pending nudge, skipping nudge match",
            thread_id=thread_id,
            nudge_type=repr(nudge_type),
            options_kind=type(options).__name__,
        )
        return NO_MATCH
    wanted = query.strip()
    for index, option in enumerate(options):
        if isinstance(option, str) and option.strip() == wanted:
            return NudgeMatch(
                matched=True, type=nudge_type or None, option_index=index
            )
    return NO_MATCH


def build_turn_trace_metadata(
    *,
    base_metadata: dict,
    input_source: str,
    nudge_response: Optional[dict],
    nudge_match: NudgeMatch,
    ui_action_only: bool,
    ff: Optional[str],
    page: Optional[str],
) -> dict:
    """LangChain config ``metadata`` for one chat turn.

    ``langfuse_tags`` becomes the trace tags (the handler strips it from
    span metadata); every other key lands on the trace metadata. None
    values are dropped: Langfuse flattens metadata into OTel attributes and
    OTel rejects None with a warning on every span.

    ``nudge_type`` / ``nudge_option_index`` are what the client clicked;
    a legacy client that only sent query_type falls back to the server
    match. ``nudge_match*`` is always the server's own view.
    """
    nudge_type: Optional[str] = None
    nudge_option_index: Optional[int] = None
    if input_source == "nudge":
        if nudge_response is not None:
            nudge_type = nudge_response["type"]
            nudge_option_index = nudge_response["option_index"]
        elif nudge_match.matched:
            nudge_type = nudge_match.type
            nudge_option_index = nudge_match.option_index

    tags = [f"input:{input_source}"]
    if nudge_type:
        tags.append(f"nudge:{nudge_type}")

    turn = {
        "langfuse_tags": tags,
        "input_source": input_source,
        "nudge_type": nudge_type,
        "nudge_option_index": nudge_option_index,
        "nudge_match": nudge_match.matched,
        "nudge_match_type": nudge_match.type,
        "nudge_match_index": nudge_match.option_index,
        "ui_action_only": bool(ui_action_only),
        "ff": ff,
        "page": page,
    }
    return {
        **base_metadata,
        **{k: v for k, v in turn.items() if v is not None},
    }
