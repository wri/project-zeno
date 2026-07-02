"""search_insights — find a past insight by free-text and re-surface it.

Digs up an insight produced earlier (this thread or any the user owns, or a
public one) and puts it back on screen. It does not generate anything — it
searches the persisted `InsightOrm` rows by their summary text, picks the best
match, and pushes it into state in the same shape `generate_insights` uses, so
the frontend renders it as a normal insight card.
"""

import re
from typing import Annotated, Optional

import structlog
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.types import Command
from sqlalchemy import Text, cast, or_, select
from sqlalchemy.orm import selectinload

from src.agent.subagents.analyst.charts.model import Insight, InsightChart
from src.agent.tool_spec import ToolCategory, ToolSpec
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


async def _search_insights(query: str, limit: int = 25) -> list[InsightOrm]:
    """Fetch candidate insights the user may see whose summary matches `query`.

    Search spans ALL of the user's conversations — it is deliberately not scoped
    to the current thread. Visibility is the shared rule from `insight_access`
    (own + public), applied in SQL so invisible rows never consume the limit.
    Matching is an ILIKE (per term or full phrase) across the summary, the
    chart titles, and the chart data text — so place names and datasets that
    only show up in a title or a data value are still found. Ranking is in Python.
    """
    terms = _terms(query)
    user_id = structlog.contextvars.get_contextvars().get("user_id")

    patterns = [f"%{_escape_like(t)}%" for t in terms]
    if query.strip():
        patterns.append(f"%{_escape_like(query.strip())}%")
    text_match = or_(
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

    async with get_session_from_pool() as session:
        result = await session.execute(
            select(InsightOrm)
            .options(selectinload(InsightOrm.charts))
            .where(visible_insights_clause(user_id), text_match)
            .order_by(InsightOrm.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


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
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=(
                            "Query too short to search past insights. Describe "
                            "the insight to recall, e.g. a place, dataset or "
                            "phrase from its summary."
                        ),
                        tool_call_id=tool_call_id,
                        status="error",
                    )
                ]
            }
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

    terms = _terms(query)
    best = max(rows, key=lambda r: (_score(r, terms, query), r.created_at))
    logger.info(
        "search_insights matched",
        insight_id=str(best.id),
        candidates=len(rows),
    )

    insight = Insight(
        charts=[InsightChart.from_orm_row(c) for c in (best.charts or [])],
        primary_insight=best.insight_text,
        follow_up_suggestions=best.follow_up_suggestions or [],
    ).stamp_insight()

    chart_titles = ", ".join(c.title for c in insight.charts) or "(no charts)"
    return Command(
        update={
            "insight_id": str(best.id),
            "insight": insight.primary_insight,
            "follow_up_suggestions": insight.follow_up_suggestions,
            "charts_data": [c.to_frontend_dict() for c in insight.charts],
            "messages": [
                ToolMessage(
                    content=(
                        f"Found a past insight ({best.id}) matching '{query}'.\n"
                        f"Charts: {chart_titles}.\n\n"
                        f"Summary: {insight.primary_insight}\n\n"
                        "STOP HERE. This insight already exists and is now on "
                        "screen. Do NOT call pull_data, generate_insights or any "
                        "other tool. Reply to the user with a one-line summary "
                        "of this recalled insight and nothing else."
                    ),
                    tool_call_id=tool_call_id,
                    status="success",
                    # Same signal as update_insight_display: the insight already
                    # exists, so the frontend re-fetches /api/insights/{id} and
                    # shows it (replacing in place, or rendering it if not yet
                    # mounted) rather than treating it as a brand-new analysis.
                    response_metadata={
                        "msg_type": "insight_updated",
                        "insight_id": str(best.id),
                    },
                )
            ],
        },
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
