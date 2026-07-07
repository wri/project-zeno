"""search_insights — find a past insight by free-text and re-surface it.

Digs up an insight produced earlier (this thread or any the user owns, or a
public one) and puts it back on screen. It does not generate anything — it
searches the persisted `InsightOrm` rows by their summary text, picks the best
match, and pushes it into state in the same shape `generate_insights` uses, so
the frontend renders it as a normal insight card.
"""

import re
from typing import Annotated, Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.types import Command
from sqlalchemy import Text, cast, or_, select
from sqlalchemy.orm import selectinload

from src.agent.subagents.analyst.charts.model import Insight
from src.agent.tool_spec import ToolCategory, ToolSpec
from src.agent.tools.common import (
    current_user_id,
    error_command,
    insight_updated_command,
)
from src.api.data_models import InsightChartOrm, InsightOrm
from src.api.repositories.insight_access import visible_insights_clause
from src.shared.database import get_session_from_pool
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


def _terms(query: str) -> list[str]:
    """Split a query into lowercased terms, dropping punctuation and tokens
    shorter than 3 characters."""
    return [t for t in re.split(r"\W+", query.lower()) if len(t) > 2]


def _escape_like(text: str) -> str:
    """Escape ILIKE metacharacters so user text matches literally."""
    return text.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


def _haystack(row: InsightOrm) -> str:
    """All searchable text for a row: summary + chart titles + chart data.

    Place names and dataset/metric names live in the chart titles and in the
    chart_data values (e.g. {"country": "Brazil"}), not just the summary — so
    they are all folded in here.
    """
    parts = [row.insight_text or ""]
    for chart in row.charts or []:
        parts.append(chart.title or "")
        parts.append(str(chart.chart_data or ""))
    return " ".join(parts).lower()


def _score(row: InsightOrm, terms: list[str], phrase: str) -> int:
    """Rough relevance: term hits across all searchable text, phrase bonus."""
    haystack = _haystack(row)
    score = sum(1 for t in terms if t in haystack)
    if phrase and phrase.lower() in haystack:
        score += len(terms) + 1  # full-phrase match outranks scattered terms
    return score


def _like_patterns(query: str) -> list[str]:
    """ILIKE patterns for a query: one per term, plus the full phrase."""
    patterns = [f"%{_escape_like(t)}%" for t in _terms(query)]
    if query.strip():
        patterns.append(f"%{_escape_like(query.strip())}%")
    return patterns


def _text_match_clause(patterns: list[str]):
    """SQL clause matching any pattern against the summary, the chart titles
    or the chart data text — so place names and datasets that only show up in
    a title or a data value are still found."""
    return or_(
        *[
            cond
            for p in patterns
            for cond in (
                InsightOrm.insight_text.ilike(p, escape="\\"),
                InsightOrm.charts.any(
                    InsightChartOrm.title.ilike(p, escape="\\")
                ),
                InsightOrm.charts.any(
                    cast(InsightChartOrm.chart_data, Text).ilike(
                        p, escape="\\"
                    )
                ),
            )
        ]
    )


async def _search_insights(query: str, limit: int = 25) -> list[InsightOrm]:
    """Fetch candidate insights the user may see whose summary matches `query`.

    Search spans ALL of the user's conversations — it is deliberately not scoped
    to the current thread. Visibility is the shared rule from `insight_access`
    (own + public), applied in SQL so invisible rows never consume the limit.
    Ranking is in Python.
    """
    async with get_session_from_pool() as session:
        result = await session.execute(
            select(InsightOrm)
            .options(selectinload(InsightOrm.charts))
            .where(
                visible_insights_clause(current_user_id()),
                _text_match_clause(_like_patterns(query)),
            )
            .order_by(InsightOrm.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


def _best_match(rows: list[InsightOrm], query: str) -> InsightOrm:
    """The highest-scoring candidate; ties go to the most recent insight."""
    terms = _terms(query)
    return max(rows, key=lambda r: (_score(r, terms, query), r.created_at))


def _recalled_message(insight_id, insight: Insight, query: str) -> str:
    """The recall report to the model — including the stop instruction, since
    the recalled insight is already on screen and terminal for this turn."""
    chart_titles = ", ".join(c.title for c in insight.charts) or "(no charts)"
    return (
        f"Found a past insight ({insight_id}) matching '{query}'.\n"
        f"Charts: {chart_titles}.\n\n"
        f"Summary: {insight.primary_insight}\n\n"
        "STOP HERE. This insight already exists and is now on screen. Do "
        "NOT call pull_data, generate_insights or any other tool. Reply to "
        "the user with a one-line summary of this recalled insight and "
        "nothing else."
    )


@tool("search_insights")
async def search_insights(
    query: str,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Find a previously generated insight by description and put it back on screen.

    Searches past insights across ALL of the user's conversations (plus public
    ones) by their summary text, picks the best match, and surfaces it so they see
    the chart and summary again — without recomputing anything. Use this when the
    user refers to an earlier finding, e.g. "show me that tree-cover insight from
    before" or "pull up the one about fires in the Amazon".
    """
    logger.info("search_insights tool called", query=query)

    # Without at least one usable pattern the ILIKE degenerates to '%%' and
    # "matches" every insight — refuse instead of recalling an arbitrary one.
    if not _terms(query) and len(query.strip()) < 3:
        return error_command(
            "Query too short to search past insights. Describe the insight "
            "to recall, e.g. a place, dataset or phrase from its summary.",
            tool_call_id,
        )

    rows = await _search_insights(query)
    if not rows:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=f"No past insight matched '{query}'.",
                        tool_call_id=tool_call_id,
                        status="success",
                    )
                ]
            }
        )

    best = _best_match(rows, query)
    logger.info(
        "search_insights matched",
        insight_id=str(best.id),
        candidates=len(rows),
    )

    insight = Insight.from_orm_row(best).stamp_insight()
    return insight_updated_command(
        best.id,
        insight,
        _recalled_message(best.id, insight, query),
        tool_call_id,
    )


SPEC = ToolSpec(
    tool=search_insights,
    category=ToolCategory.PRIMITIVE,
    prompt_fragment=(
        "- search_insights(query): find a previously generated insight by "
        "description and put it back on screen (chart + summary), without "
        "recomputing. Use when the user refers to an earlier finding, e.g. "
        "'show that insight about fires in the Amazon again'. This is a "
        "TERMINAL action: after it returns, do NOT call pull_data, "
        "generate_insights or any other tool — just give a one-line summary "
        "of the recalled insight and stop."
    ),
)
