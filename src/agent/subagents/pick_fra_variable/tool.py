"""FAO-FRA variable-selection subagent.

The orchestrator exposes this as the `pick_fra_variable` tool. Internally it
runs one small-LLM call against `VARIABLE_MAP` to pick the single best
variable for the user's question. The chosen variable name is surfaced via
ToolMessage and emitted as a progress event; the orchestrator then passes it
into `query_fra_data`.

The selection is intentionally returned in the ToolMessage rather than stashed
in state — the subagent stays pure and re-callable, and the orchestrator can
re-pick if the first attempt looks wrong downstream.
"""

from typing import Annotated, Optional

from langchain_core.messages import ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.types import Command
from pydantic import BaseModel, Field

from src.agent.llms import SMALL_MODEL
from src.agent.subagents.pick_fra_variable.prompts import (
    VARIABLE_SELECTOR_PROMPT,
)
from src.agent.subagents.pick_fra_variable.variable_map import (
    VALID_VARIABLES,
    VARIABLE_MAP,
    render_variable_table,
)
from src.agent.subagents.progress import emit_progress
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


# The set of accepted variable names is the keys of VARIABLE_MAP; mirroring
# that into a runtime-validated string field is enough — using a Literal
# would require regenerating the type each time VARIABLE_MAP changes.
class VariableSelection(BaseModel):
    """Structured output: the single best FAO FRA variable name."""

    variable: str = Field(
        description=(
            "The chosen FAO FRA variable name. MUST be one of the names "
            "from the variables table; do not invent new names."
        )
    )
    reason: str = Field(
        description=(
            "One short sentence explaining the choice, in the language of "
            "the user's query."
        )
    )


VARIABLE_SELECTION_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", VARIABLE_SELECTOR_PROMPT),
        ("user", "{question}"),
    ]
)


class VariableSelector:
    """Picks the FAO FRA variable that best answers the user's question.

    Mirrors the shape of `DatasetSelector` (subagents/pick_dataset). One
    LLM call against the variable table; returns a `Command` carrying a
    ToolMessage with the chosen variable name + reason. The orchestrator
    extracts the variable from that message when it next calls
    `query_fra_data`.
    """

    async def resolve(
        self,
        question: str,
        tool_call_id: Optional[str] = None,
    ) -> Command:
        logger.info("PICK-FRA-VARIABLE: resolving query")
        selection = await self._select(question)

        if selection.variable not in VARIABLE_MAP:
            # The LLM hallucinated a name. Surface the closed set so the
            # orchestrator can re-call with a hint.
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=(
                                f"'{selection.variable}' is not a recognised "
                                "FAO FRA variable. Valid options are: "
                                f"{', '.join(VALID_VARIABLES)}."
                            ),
                            tool_call_id=tool_call_id,
                            status="success",
                            response_metadata={"msg_type": "human_feedback"},
                        )
                    ]
                }
            )

        entry = VARIABLE_MAP[selection.variable]
        emit_progress(
            "pick_fra_variable",
            "selected",
            f"Selected variable: {selection.variable}",
        )

        tool_message = (
            f"Selected FAO FRA variable: {selection.variable} "
            f"({entry['unit']}) — {entry['description']}. "
            f"Reason: {selection.reason}\n\n"
            f'Call query_fra_data with variable="{selection.variable}" '
            "next."
        )
        return Command(
            update={
                "messages": [
                    ToolMessage(tool_message, tool_call_id=tool_call_id)
                ]
            }
        )

    async def _select(self, question: str) -> VariableSelection:
        chain = VARIABLE_SELECTION_PROMPT | SMALL_MODEL.with_structured_output(
            VariableSelection
        )
        return await chain.ainvoke(
            {
                "question": question,
                "variable_table": render_variable_table(),
            }
        )


@tool("pick_fra_variable")
async def pick_fra_variable(
    question: str,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Pick the FAO FRA 2025 variable that best answers the user's request.

    Pass the user's question verbatim — e.g. "How much carbon does Brazil's
    forest store?" or "Forest ownership in Sweden". This subagent picks
    exactly one variable (carbon_stock, ownership, forest_area, …) by
    running its own LLM step against the typed VARIABLE_MAP.

    Use this BEFORE calling query_fra_data. The selected variable name is
    in the ToolMessage; pass it to query_fra_data as the `variable` arg.

    Country-level only — pick_aoi must have resolved a country (gadm
    subtype=country) first.
    """
    return await VariableSelector().resolve(question, tool_call_id)
