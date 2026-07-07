"""update_insight_display — restyle an existing insight, no new data.

Where `generate_insights` pulls data, runs code and builds an insight from
scratch, this tool only touches the *display* layer of an insight that already
exists: the narrative text, follow-up suggestions, chart titles, chart types and
which existing columns each chart maps to. It never pulls data or runs code — the
underlying chart rows are preserved untouched.

The target is the current insight in state (the last one generated this thread)
unless an explicit ``insight_id`` is given. The revised insight is persisted in
place and pushed back onto state so the frontend re-renders it.
"""

from typing import Annotated, Dict, Optional
from uuid import UUID

from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.agent.subagents.analyst.charts.model import Insight, InsightChart
from src.agent.subagents.analyst.display_reviser import (
    InsightDisplayReviser,
    RevisedChart,
    RevisedInsight,
)
from src.agent.tool_spec import ToolCategory, ToolSpec
from src.agent.tools.common import (
    error_command,
    insight_updated_command,
    require_current_user_id,
)
from src.api.data_models import InsightOrm
from src.api.repositories.insight_access import is_editable_by_user
from src.api.repositories.insight_writer import update_insight
from src.shared.database import get_session_from_pool
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


async def _load_editable_insight(insight_id: str) -> Optional[InsightOrm]:
    """Load an insight (with charts) the current user is allowed to edit.

    Editable means the current user owns it (`insight_access` rule). Public or
    owner-less insights are read-only; without an authenticated user nothing
    is editable. Malformed ids are treated as not found.
    """
    try:
        target = UUID(insight_id)
    except ValueError:
        return None
    async with get_session_from_pool() as session:
        result = await session.execute(
            select(InsightOrm)
            .options(selectinload(InsightOrm.charts))
            .where(InsightOrm.id == target)
        )
        row = result.scalar_one_or_none()
    if row is None or not is_editable_by_user(
        row, require_current_user_id("update_insight_display")
    ):
        return None
    return row


def _referenced_columns(chart: RevisedChart) -> set[str]:
    """Every non-empty column a revised chart points at."""
    named = {
        chart.x_axis,
        chart.y_axis,
        chart.color_field,
        chart.stack_field,
        chart.group_field,
    }
    named.update(chart.series_fields)
    return {name for name in named if name}


def _apply_revision(
    originals: list[InsightChart], revised: RevisedInsight
) -> Insight:
    """Merge the revised display fields back onto the fixed chart data.

    Charts are matched by `position`; the original `chart_data` is always kept.
    A revision that references a column the data does not have is dropped (the
    original chart is left as-is) so we never produce a chart that can't render.
    """
    revised_by_pos = {rc.position: rc for rc in revised.charts}

    new_charts: list[InsightChart] = []
    for original in originals:
        rc = revised_by_pos.get(original.position)
        available = set(original.available_columns())
        if rc is None or not _referenced_columns(rc) <= available:
            if rc is not None:
                logger.warning(
                    "update_insight_display: revision references unknown "
                    "columns, keeping original chart",
                    position=original.position,
                )
            new_charts.append(original)
            continue
        new_charts.append(
            InsightChart(
                position=original.position,
                title=rc.title,
                chart_type=rc.chart_type,
                x_axis=rc.x_axis,
                y_axis=rc.y_axis,
                color_field=rc.color_field,
                stack_field=rc.stack_field,
                group_field=rc.group_field,
                series_fields=rc.series_fields,
                chart_data=original.chart_data,
            )
        )

    return Insight(
        charts=new_charts,
        primary_insight=revised.primary_insight,
        follow_up_suggestions=revised.follow_up_suggestions,
    ).stamp_insight()


@tool("update_insight_display")
async def update_insight_display(
    instruction: str,
    insight_id: Optional[str] = None,
    state: Annotated[Dict, InjectedState] | None = None,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Restyle an existing insight without pulling new data or running code.

    Use this for presentation-only changes the user asks for on an insight that
    already exists: reword the summary or follow-up suggestions, rename a chart,
    change a chart type (e.g. bar -> line), or re-map a chart to other columns it
    already has. It cannot add data, compute new metrics or create charts — use
    generate_insights for anything that needs new data or analysis.

    By default it updates the most recent insight in this conversation; pass
    `insight_id` to target a specific one (e.g. an insight visible on screen).
    """
    target_id = insight_id or (state or {}).get("insight_id")
    if not target_id:
        return error_command(
            "No insight to update. Generate an insight first, or pass an "
            "insight_id.",
            tool_call_id,
        )

    logger.info("update_insight_display tool called", insight_id=target_id)

    row = await _load_editable_insight(str(target_id))
    if row is None:
        return error_command(
            f"Insight {target_id} not found or not editable.", tool_call_id
        )

    current = Insight.from_orm_row(row)
    revised = await InsightDisplayReviser().revise(current, instruction)

    try:
        updated = _apply_revision(current.charts, revised)
    except ValueError as exc:
        logger.warning("update_insight_display: invalid revision: %s", exc)
        return error_command(
            f"Could not apply that change: {exc}", tool_call_id
        )

    if not await update_insight(str(target_id), updated):
        return error_command(
            f"Insight {target_id} disappeared before it could be updated.",
            tool_call_id,
        )

    chart_titles = ", ".join(c.title for c in updated.charts)
    return insight_updated_command(
        target_id,
        updated,
        (
            f"Updated insight {target_id}. Charts: {chart_titles}.\n\n"
            f"Summary: {updated.primary_insight}"
        ),
        tool_call_id,
    )


SPEC = ToolSpec(
    tool=update_insight_display,
    category=ToolCategory.SUBAGENT,
    prompt_fragment=(
        "- update_insight_display(instruction, insight_id?): restyle an "
        "existing insight without new data — reword the summary or follow-ups, "
        "rename charts, change a chart type, or re-map a chart to columns it "
        "already has. Defaults to the most recent insight; pass insight_id to "
        "target a specific one. Use generate_insights when new data or "
        "analysis is needed."
    ),
)
