"""Centralized insight persistence shared by both insight paths.

Both the agent/chat path (`Analyst.analyze`) and the deterministic
`/api/analyze` job write the same `InsightOrm` + `InsightChartOrm` rows. This is
the single place that mapping lives, driven by the canonical `Insight`.
"""

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.agent.subagents.analyst.charts.model import Insight
from src.api.data_models import InsightChartOrm, InsightOrm
from src.shared.database import get_session_from_pool
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


async def persist_insight(
    insight: Insight,
    *,
    user_id: Optional[str],
    thread_id: str,
    statistics_ids: Optional[list[str]] = None,
    codeact_parts: Optional[list[dict]] = None,
) -> str:
    """Persist an insight and its charts; return the new insight id (str).

    `codeact_parts` are the base64-encoded code/output blocks (as produced by
    `ExecutionResult.get_encoded_parts`); empty for deterministic charts.
    """
    statistics_ids = statistics_ids or []
    codeact_parts = codeact_parts or []

    async with get_session_from_pool() as session:
        insight_orm = InsightOrm(
            user_id=user_id,
            thread_id=thread_id,
            insight_text=insight.primary_insight,
            follow_up_suggestions=insight.follow_up_suggestions,
            statistics_ids=statistics_ids,
            codeact_types=[p["type"] for p in codeact_parts],
            codeact_contents=[p["content"] for p in codeact_parts],
        )
        session.add(insight_orm)
        await session.flush()

        session.add_all(
            InsightChartOrm(insight_id=insight_orm.id, **chart.to_orm_kwargs())
            for chart in insight.charts
        )

        await session.commit()
        await session.refresh(insight_orm)
        insight_id = str(insight_orm.id)

    logger.info(
        "insight_persisted",
        insight_id=insight_id,
        thread_id=thread_id,
        charts_count=len(insight.charts),
    )
    return insight_id


async def update_insight(insight_id: str, insight: Insight) -> bool:
    """Rewrite an existing insight's display layer in place.

    Only the generative/presentation fields are replaced — narrative text,
    follow-up suggestions and the chart specs (titles, types, field mappings,
    per-chart `chart_data`). Ownership (`user_id`/`thread_id`), `statistics_ids`,
    the `codeact_*` provenance and `created_at` are deliberately left untouched:
    this path restyles an insight, it does not pull new data or re-run code.

    Returns ``True`` on success, ``False`` if the insight no longer exists
    (or the id is malformed).
    """
    try:
        target = UUID(insight_id)
    except ValueError:
        return False

    async with get_session_from_pool() as session:
        result = await session.execute(
            select(InsightOrm)
            .options(selectinload(InsightOrm.charts))
            .where(InsightOrm.id == target)
        )
        insight_orm = result.scalar_one_or_none()
        if insight_orm is None:
            return False

        insight_orm.insight_text = insight.primary_insight
        insight_orm.follow_up_suggestions = insight.follow_up_suggestions
        # Reassigning the collection lets the delete-orphan cascade drop the old
        # chart rows and insert the revised ones in their place.
        insight_orm.charts = [
            InsightChartOrm(**chart.to_orm_kwargs())
            for chart in insight.charts
        ]

        await session.commit()

    logger.info(
        "insight_updated",
        insight_id=insight_id,
        charts_count=len(insight.charts),
    )
    return True
