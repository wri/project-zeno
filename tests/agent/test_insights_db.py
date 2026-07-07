"""DB-integration tests for insight recall and in-place update.

These exercise the real SQL paths the tool unit tests mock out: the shared
visibility clause in `_search_insights` (including its interaction with
LIMIT), the ownership rule in `_load_editable_insight`, and the chart
replacement + provenance preservation in `update_insight`.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import func, select

from src.agent.subagents.analyst.charts.model import Insight, InsightChart
from src.agent.tools.search_insights import _search_insights
from src.agent.tools.update_insight_display import _load_editable_insight
from src.api.data_models import InsightChartOrm, InsightOrm
from src.api.repositories.insight_writer import update_insight
from src.shared.request_context import bound_user_id
from tests.conftest import async_session_maker


async def _insert_insight(
    *,
    user_id,
    text,
    is_public=False,
    created_at=datetime(2026, 6, 1),
    chart_title="Annual tree cover loss",
    chart_data=None,
):
    async with async_session_maker() as session:
        row = InsightOrm(
            user_id=user_id,
            thread_id="thread-1",
            insight_text=text,
            follow_up_suggestions=["old follow-up"],
            statistics_ids=["stat-1"],
            codeact_types=["code"],
            codeact_contents=["cHJpbnQoKQ=="],
            is_public=is_public,
            created_at=created_at,
        )
        session.add(row)
        await session.flush()
        session.add(
            InsightChartOrm(
                insight_id=row.id,
                position=0,
                title=chart_title,
                chart_type="bar",
                x_axis="year",
                y_axis="loss",
                chart_data=chart_data or [{"year": 2020, "loss": 5}],
            )
        )
        await session.commit()
        return row.id


def _revised_insight():
    return Insight(
        charts=[
            InsightChart(
                position=0,
                title="New title",
                chart_type="line",
                x_axis="year",
                y_axis="loss",
                chart_data=[{"year": 2020, "loss": 5}],
            )
        ],
        primary_insight="New summary.",
        follow_up_suggestions=["new follow-up"],
    ).stamp_insight()


async def test_search_returns_own_and_public_only(user, user_ds):
    own = await _insert_insight(
        user_id=user.id, text="Tree cover loss in the Amazon rose."
    )
    theirs_public = await _insert_insight(
        user_id=user_ds.id,
        text="Amazon fires spiked in 2025.",
        is_public=True,
    )
    await _insert_insight(  # other's private: must not appear
        user_id=user_ds.id, text="Private Amazon deforestation note."
    )
    await _insert_insight(  # ownerless: must not appear
        user_id=None, text="Ownerless Amazon CLI insight."
    )

    with bound_user_id(user.id):
        rows = await _search_insights("amazon")

    assert {row.id for row in rows} == {own, theirs_public}


async def test_invisible_rows_do_not_consume_the_limit(user, user_ds):
    own = await _insert_insight(
        user_id=user.id,
        text="Tree cover loss in the Amazon rose.",
        created_at=datetime(2026, 6, 1),
    )
    # Newer matching rows the user may not see: with the visibility filter
    # applied after LIMIT these would crowd out the real match.
    for day in range(2, 5):
        await _insert_insight(
            user_id=user_ds.id,
            text="Private Amazon note.",
            created_at=datetime(2026, 6, day),
        )

    with bound_user_id(user.id):
        rows = await _search_insights("amazon", limit=1)

    assert [row.id for row in rows] == [own]


async def test_search_matches_chart_title_and_data(user):
    insight_id = await _insert_insight(
        user_id=user.id,
        text="Deforestation summary.",
        chart_title="Fires in Para",
        chart_data=[{"country": "Brazil", "fires": 120}],
    )

    with bound_user_id(user.id):
        by_title = await _search_insights("para fires")
        by_data = await _search_insights("brazil")

    assert insight_id in {row.id for row in by_title}
    assert insight_id in {row.id for row in by_data}


async def test_load_editable_insight_owner_only(user, user_ds):
    own = await _insert_insight(user_id=user.id, text="Mine.")
    theirs = await _insert_insight(
        user_id=user_ds.id, text="Theirs.", is_public=True
    )
    ownerless = await _insert_insight(user_id=None, text="Ownerless.")

    with bound_user_id(user.id):
        assert (await _load_editable_insight(str(own))).id == own
        assert await _load_editable_insight(str(theirs)) is None
        assert await _load_editable_insight(str(ownerless)) is None
        assert await _load_editable_insight("not-a-uuid") is None

    # Without an authenticated user nothing is editable.
    assert await _load_editable_insight(str(own)) is None


async def test_update_insight_replaces_charts_preserves_provenance(user):
    insight_id = await _insert_insight(user_id=user.id, text="Old summary.")

    assert await update_insight(str(insight_id), _revised_insight()) is True

    async with async_session_maker() as session:
        row = await session.get(InsightOrm, insight_id)
        charts = (
            (
                await session.execute(
                    select(InsightChartOrm).where(
                        InsightChartOrm.insight_id == insight_id
                    )
                )
            )
            .scalars()
            .all()
        )
        orphans = await session.scalar(
            select(func.count())
            .select_from(InsightChartOrm)
            .where(InsightChartOrm.insight_id != insight_id)
        )

    # Display layer replaced...
    assert row.insight_text == "New summary."
    assert row.follow_up_suggestions == ["new follow-up"]
    assert len(charts) == 1
    assert charts[0].title == "New title"
    assert charts[0].chart_type == "line"
    assert orphans == 0
    # ...provenance untouched.
    assert row.user_id == user.id
    assert row.thread_id == "thread-1"
    assert row.statistics_ids == ["stat-1"]
    assert row.codeact_types == ["code"]
    assert row.codeact_contents == ["cHJpbnQoKQ=="]
    assert row.created_at == datetime(2026, 6, 1)


async def test_update_insight_missing_or_malformed_id():
    assert await update_insight(str(uuid4()), _revised_insight()) is False
    assert await update_insight("not-a-uuid", _revised_insight()) is False
