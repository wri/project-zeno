"""DB-integration tests for dashboard persistence and access.

These exercise the real SQL paths the tool unit tests mock out: the
dashboard_writer repository (create/widget lifecycle/publish cascade/delete),
the owner-only rule through the add_to_dashboard tool, and the FK cascade
from insights to widgets. The single-area constraint deliberately does NOT
live here — it is API validation (max_length=1), so the repo happily stores
multiple AOIs (portfolio-ready schema).
"""

from uuid import UUID, uuid4

import structlog
from sqlalchemy import select

from src.agent.tools.add_to_dashboard import add_to_dashboard
from src.api.data_models import (
    DashboardAoiOrm,
    DashboardOrm,
    DashboardWidgetOrm,
    InsightOrm,
)
from src.api.repositories import dashboard_writer
from tests.conftest import async_session_maker

PARANA = {
    "source": "gadm",
    "src_id": "BRA.16_1",
    "subtype": "state-province",
    "name": "Paraná",
}
BRAZIL = {
    "source": "gadm",
    "src_id": "BRA",
    "subtype": "country",
    "name": "Brazil",
}


async def _insert_insight(*, user_id, text="An insight.", is_public=False):
    async with async_session_maker() as session:
        row = InsightOrm(
            user_id=user_id,
            thread_id="thread-1",
            insight_text=text,
            is_public=is_public,
        )
        session.add(row)
        await session.commit()
        return row.id


async def _widget_ids(dashboard_id) -> list:
    async with async_session_maker() as session:
        result = await session.execute(
            select(DashboardWidgetOrm.id)
            .where(DashboardWidgetOrm.dashboard_id == UUID(str(dashboard_id)))
            .order_by(DashboardWidgetOrm.position)
        )
        return list(result.scalars().all())


async def test_create_and_get_dashboard(user):
    dashboard_id = await dashboard_writer.create_dashboard(
        user_id=user.id,
        name="Paraná",
        description="Forest monitoring",
        aois=[PARANA],
    )

    row = await dashboard_writer.get_dashboard(dashboard_id)
    assert row.name == "Paraná"
    assert row.description == "Forest monitoring"
    assert row.user_id == user.id
    assert row.is_public is False
    assert [(a.source, a.src_id, a.name) for a in row.aois] == [
        ("gadm", "BRA.16_1", "Paraná")
    ]
    assert row.widgets == []

    assert await dashboard_writer.get_dashboard(str(uuid4())) is None
    assert await dashboard_writer.get_dashboard("not-a-uuid") is None


async def test_repo_accepts_multiple_aois(user):
    # Portfolio-ready schema: single-area is API validation, not a repo rule.
    dashboard_id = await dashboard_writer.create_dashboard(
        user_id=user.id, name="Portfolio", aois=[PARANA, BRAZIL]
    )
    row = await dashboard_writer.get_dashboard(dashboard_id)
    assert [a.position for a in row.aois] == [0, 1]
    assert [a.name for a in row.aois] == ["Paraná", "Brazil"]


async def test_widget_add_reorder_remove(user):
    dashboard_id = await dashboard_writer.create_dashboard(
        user_id=user.id, name="Paraná", aois=[PARANA]
    )
    insight_id = await _insert_insight(user_id=user.id)

    w1 = await dashboard_writer.add_widget(
        dashboard_id, widget_type="insight", insight_id=str(insight_id)
    )
    w2 = await dashboard_writer.add_widget(
        dashboard_id,
        widget_type="map",
        config={"dataset_id": 4, "default_view": "map"},
    )

    row = await dashboard_writer.get_dashboard(dashboard_id)
    # Position defaults to max+1 (append at the end).
    assert [(str(w.id), w.position) for w in row.widgets] == [
        (w1, 0),
        (w2, 1),
    ]
    assert row.widgets[0].insight_id == insight_id
    assert row.widgets[1].config == {"dataset_id": 4, "default_view": "map"}

    # Reorder + config update.
    assert await dashboard_writer.update_widget(w2, position=0) is True
    assert (
        await dashboard_writer.update_widget(
            w1, position=1, config={"default_view": "table"}
        )
        is True
    )
    row = await dashboard_writer.get_dashboard(dashboard_id)
    assert [str(w.id) for w in row.widgets] == [w2, w1]
    assert row.widgets[1].config == {"default_view": "table"}

    # Remove: the widget goes, the insight stays.
    assert await dashboard_writer.remove_widget(w1) is True
    assert await _widget_ids(dashboard_id) == [UUID(w2)]
    async with async_session_maker() as session:
        assert await session.get(InsightOrm, insight_id) is not None

    # Missing / malformed ids are not-found, not errors.
    assert await dashboard_writer.remove_widget(w1) is False
    assert await dashboard_writer.update_widget("not-a-uuid") is False
    assert (
        await dashboard_writer.add_widget(str(uuid4()), widget_type="map")
        is None
    )


async def test_add_to_dashboard_tool_owner_only_edit(user, user_ds):
    """The full tool path: own dashboard editable, someone else's is not."""
    theirs = await dashboard_writer.create_dashboard(
        user_id=user_ds.id, name="Theirs", aois=[PARANA]
    )
    mine = await dashboard_writer.create_dashboard(
        user_id=user.id, name="Mine", aois=[PARANA]
    )
    insight_id = await _insert_insight(user_id=user.id)

    with structlog.contextvars.bound_contextvars(user_id=user.id):
        denied = await add_to_dashboard.coroutine(
            insight_id=str(insight_id),
            dashboard_id=theirs,
            state={},
            tool_call_id="t1",
        )
        allowed = await add_to_dashboard.coroutine(
            insight_id=str(insight_id),
            dashboard_id=mine,
            state={},
            tool_call_id="t2",
        )

    assert denied.update["messages"][0].status == "error"
    assert await _widget_ids(theirs) == []

    message = allowed.update["messages"][0]
    assert message.status == "success"
    assert message.response_metadata["msg_type"] == "dashboard_updated"
    assert message.response_metadata["dashboard_id"] == mine
    assert allowed.update["dashboard_id"] == mine
    assert len(await _widget_ids(mine)) == 1


async def test_update_and_delete_dashboard(user):
    dashboard_id = await dashboard_writer.create_dashboard(
        user_id=user.id, name="Old name", aois=[PARANA]
    )
    insight_id = await _insert_insight(user_id=user.id)
    await dashboard_writer.add_widget(
        dashboard_id, widget_type="insight", insight_id=str(insight_id)
    )

    assert (
        await dashboard_writer.update_dashboard(
            dashboard_id, name="New name", description="Now described"
        )
        is True
    )
    row = await dashboard_writer.get_dashboard(dashboard_id)
    assert (row.name, row.description) == ("New name", "Now described")

    # Delete removes the dashboard with its AOIs and widgets ...
    assert await dashboard_writer.delete_dashboard(dashboard_id) is True
    assert await dashboard_writer.get_dashboard(dashboard_id) is None
    async with async_session_maker() as session:
        aois = (await session.execute(select(DashboardAoiOrm))).scalars().all()
        widgets = (
            (await session.execute(select(DashboardWidgetOrm))).scalars().all()
        )
        # ... but the referenced insight is left intact.
        insight = await session.get(InsightOrm, insight_id)
    assert aois == []
    assert widgets == []
    assert insight is not None

    assert await dashboard_writer.delete_dashboard(dashboard_id) is False
    assert await dashboard_writer.delete_dashboard("not-a-uuid") is False
    assert await dashboard_writer.update_dashboard("not-a-uuid") is False


async def test_publish_cascades_to_referenced_insights(user, user_ds):
    dashboard_id = await dashboard_writer.create_dashboard(
        user_id=user.id, name="Paraná", aois=[PARANA]
    )
    private_insight = await _insert_insight(user_id=user.id)
    public_insight = await _insert_insight(user_id=user.id, is_public=True)
    unreferenced = await _insert_insight(user_id=user.id)
    for insight_id in (private_insight, public_insight):
        await dashboard_writer.add_widget(
            dashboard_id, widget_type="insight", insight_id=str(insight_id)
        )

    publicized = await dashboard_writer.set_dashboard_public(
        dashboard_id, True
    )
    # Only the insight that actually flipped is reported.
    assert publicized == [str(private_insight)]

    async with async_session_maker() as session:
        assert (await session.get(DashboardOrm, UUID(dashboard_id))).is_public
        assert (await session.get(InsightOrm, private_insight)).is_public
        assert (await session.get(InsightOrm, public_insight)).is_public
        # Insights not on the dashboard are untouched.
        assert not (await session.get(InsightOrm, unreferenced)).is_public

    # Unpublishing does not cascade — the insights may be shared elsewhere.
    assert (
        await dashboard_writer.set_dashboard_public(dashboard_id, False) == []
    )
    async with async_session_maker() as session:
        assert not (
            await session.get(DashboardOrm, UUID(dashboard_id))
        ).is_public
        assert (await session.get(InsightOrm, private_insight)).is_public

    assert (
        await dashboard_writer.set_dashboard_public(str(uuid4()), True) is None
    )
    assert (
        await dashboard_writer.set_dashboard_public("not-a-uuid", True) is None
    )


async def test_deleting_insight_cascades_widget_removal(user):
    dashboard_id = await dashboard_writer.create_dashboard(
        user_id=user.id, name="Paraná", aois=[PARANA]
    )
    insight_id = await _insert_insight(user_id=user.id)
    await dashboard_writer.add_widget(
        dashboard_id, widget_type="insight", insight_id=str(insight_id)
    )
    keeper = await dashboard_writer.add_widget(
        dashboard_id, widget_type="map", config={"dataset_id": 4}
    )

    async with async_session_maker() as session:
        insight = await session.get(InsightOrm, insight_id)
        await session.delete(insight)
        await session.commit()

    # The widget referencing the insight is silently dropped (FK ON DELETE
    # CASCADE); the dashboard and its other widgets survive.
    assert await _widget_ids(dashboard_id) == [UUID(keeper)]
    assert await dashboard_writer.get_dashboard(dashboard_id) is not None
