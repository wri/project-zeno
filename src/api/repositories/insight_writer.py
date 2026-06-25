"""Centralized insight persistence shared by both insight paths.

Both the agent/chat path (`Analyst.analyze`) and the deterministic
`/api/analyze` job write the same `InsightOrm` + `InsightChartOrm` rows. This is
the single place that mapping lives, driven by the canonical `Insight`.
"""

from typing import Optional

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
        insight = InsightOrm(
            user_id=user_id,
            thread_id=thread_id,
            insight_text=insight.primary_insight,
            follow_up_suggestions=insight.follow_up_suggestions,
            statistics_ids=statistics_ids,
            codeact_types=[p["type"] for p in codeact_parts],
            codeact_contents=[p["content"] for p in codeact_parts],
        )
        session.add(insight)
        await session.flush()

        session.add_all(
            InsightChartOrm(insight_id=insight.id, **chart.to_orm_kwargs())
            for chart in insight.charts
        )

        await session.commit()
        await session.refresh(insight)
        insight_id = str(insight.id)

    logger.info(
        "insight_persisted",
        insight_id=insight_id,
        thread_id=thread_id,
        charts_count=len(insight.charts),
    )
    return insight_id
