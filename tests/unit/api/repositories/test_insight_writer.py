"""Unit tests for insight_writer's malformed-id contract."""

from unittest.mock import MagicMock

import pytest

from src.agent.subagents.analyst.charts.model import Insight
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
