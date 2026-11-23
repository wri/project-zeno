"""Unit tests for insight_writer's malformed-id contract."""

from unittest.mock import MagicMock

import pytest

from src.agent.subagents.analyst.charts.model import Insight, InsightChart
from src.api.repositories import insight_writer
from src.shared import text_sanitize


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


def test_add_insight_rows_tags_chart_row_warnings_as_create(monkeypatch):
    logger = MagicMock()
    monkeypatch.setattr(text_sanitize, "logger", logger)
    insight = Insight(
        charts=[
            InsightChart(
                position=0,
                title="Loss by state",
                chart_type="bar",
                x_axis="state",
                y_axis="loss",
                chart_data=[{"state": "Piau\x00", "loss": 5}],
            )
        ],
        primary_insight="Tree cover loss by state.",
    )

    insight_writer.add_insight_rows(
        MagicMock(),
        insight,
        user_id=None,
        thread_id="thread-1",
        statistics_ids_exact=True,
    )

    (call,) = logger.warning.call_args_list
    assert call.args == ("control_chars_stripped",)
    assert call.kwargs["field"] == "chart_row:create"


@pytest.mark.parametrize("exact", [True, False])
def test_add_insight_rows_stores_whether_the_links_are_exact(exact):
    session = MagicMock()
    row = insight_writer.add_insight_rows(
        session,
        Insight(charts=[], primary_insight="text"),
        user_id="user-1",
        thread_id="thread-1",
        statistics_ids=["stat-1"],
        statistics_ids_exact=exact,
    )
    assert row.statistics_ids == ["stat-1"]
    assert row.statistics_ids_exact is exact


def test_every_writer_must_decide_whether_the_links_are_exact():
    with pytest.raises(TypeError, match="statistics_ids_exact"):
        insight_writer.add_insight_rows(  # type: ignore[call-arg]
            MagicMock(),
            Insight(charts=[], primary_insight="text"),
            user_id="user-1",
            thread_id="thread-1",
        )
