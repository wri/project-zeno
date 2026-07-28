"""Unit tests for insight_writer's malformed-id and no-commit contracts."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent.subagents.analyst.charts.model import Insight, InsightChart
from src.api.repositories import insight_writer


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    """Fail the test if update_insight opens a DB session."""
    pool = MagicMock(side_effect=AssertionError("must not open a DB session"))
    monkeypatch.setattr(insight_writer, "get_session_from_pool", pool)


@pytest.mark.parametrize("bad", ["not-a-uuid", ""])
async def test_update_insight_malformed_id_is_false(bad):
    insight = Insight(
        charts=[], primary_insight="text", follow_up_suggestions=[]
    )
    assert await insight_writer.update_insight(bad, insight) is False


async def test_add_insight_flushes_but_never_commits():
    """add_insight participates in the caller's transaction: it must flush
    (so the insight id materialises) but never commit — the transaction
    boundary belongs to the caller."""
    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    insight = Insight(
        charts=[
            InsightChart(
                position=0,
                title="t",
                chart_type="bar",
                x_axis="x",
                y_axis="y",
                chart_data=[{"x": 1, "y": 2.0}],
            )
        ],
    )

    row = await insight_writer.add_insight(
        session, insight, user_id="u-1", thread_id="t-1"
    )

    session.add.assert_called_once_with(row)
    session.flush.assert_awaited_once()
    session.add_all.assert_called_once()
    session.commit.assert_not_awaited()
