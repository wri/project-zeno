"""Tests for the dashboard section agent tools and section placement.

Sections are the one level of grouping a dashboard has. These cover the two
section primitives (add_dashboard_section, edit_dashboard_section) and the
`section` argument the widget-adding tools take, including how a section is
named — by title or by id.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from src.agent.tools.add_dashboard_section import add_dashboard_section
from src.agent.tools.add_to_dashboard import add_to_dashboard
from src.agent.tools.edit_dashboard_section import edit_dashboard_section
from src.agent.tools.move_dashboard_widget import move_dashboard_widget
from src.api.repositories import dashboard_writer
from src.shared.request_context import bound_user_id


def _content(command):
    return command.update["messages"][0].content


def _status(command):
    return command.update["messages"][0].status


def _section(title="Deforestation", description=None, position=0):
    return SimpleNamespace(
        id=uuid4(), title=title, description=description, position=position
    )


def _dashboard(user_id="user-1", name="Paraná", sections=None):
    return SimpleNamespace(
        id=uuid4(),
        user_id=user_id,
        name=name,
        is_public=False,
        sections=sections or [],
    )


def _insight(user_id="user-1"):
    return SimpleNamespace(
        id=uuid4(),
        user_id=user_id,
        is_public=False,
        insight_text="Tree cover loss rose 12%.",
    )


def _get_dashboard(dashboard):
    return patch(
        "src.api.repositories.dashboard_writer.get_dashboard",
        new=AsyncMock(return_value=dashboard),
    )


# ---------------------------------------------------------------------------
# add_dashboard_section
# ---------------------------------------------------------------------------
async def test_add_section_writes_and_reports_the_title():
    dashboard = _dashboard()
    state = {"dashboard_id": str(dashboard.id)}
    with (
        _get_dashboard(dashboard),
        patch(
            "src.api.repositories.dashboard_writer.add_section",
            new=AsyncMock(return_value="section-1"),
        ) as add_section,
        bound_user_id("user-1"),
    ):
        command = await add_dashboard_section.coroutine(
            title="  Deforestation  ",
            description="  Where forest is being lost.  ",
            state=state,
            tool_call_id="t1",
        )

    assert _status(command) == "success"
    add_section.assert_awaited_once_with(
        str(dashboard.id),
        title="Deforestation",
        description="Where forest is being lost.",
        position=None,
    )
    assert "Deforestation" in _content(command)
    assert command.update["dashboard_id"] == str(dashboard.id)


async def test_add_section_rejects_an_empty_title():
    dashboard = _dashboard()
    with _get_dashboard(dashboard), bound_user_id("user-1"):
        command = await add_dashboard_section.coroutine(
            title="   ",
            state={"dashboard_id": str(dashboard.id)},
            tool_call_id="t1",
        )
    assert _status(command) == "error"
    assert "title is empty" in _content(command)


async def test_add_section_refuses_a_duplicate_title():
    existing = _section("Deforestation")
    dashboard = _dashboard(sections=[existing])
    with (
        _get_dashboard(dashboard),
        patch(
            "src.api.repositories.dashboard_writer.add_section",
            new=AsyncMock(),
        ) as add_section,
        bound_user_id("user-1"),
    ):
        command = await add_dashboard_section.coroutine(
            title="deforestation",
            state={"dashboard_id": str(dashboard.id)},
            tool_call_id="t1",
        )
    assert _status(command) == "error"
    assert str(existing.id) in _content(command)
    add_section.assert_not_awaited()


async def test_add_section_without_a_dashboard_errors():
    with bound_user_id("user-1"):
        command = await add_dashboard_section.coroutine(
            title="Deforestation", state={}, tool_call_id="t1"
        )
    assert _status(command) == "error"
    assert "No dashboard" in _content(command)


async def test_add_section_on_someone_elses_dashboard_errors():
    dashboard = _dashboard(user_id="other-user")
    with _get_dashboard(dashboard), bound_user_id("user-1"):
        command = await add_dashboard_section.coroutine(
            title="Deforestation",
            state={"dashboard_id": str(dashboard.id)},
            tool_call_id="t1",
        )
    assert _status(command) == "error"
    assert "not editable" in _content(command)


# ---------------------------------------------------------------------------
# edit_dashboard_section
# ---------------------------------------------------------------------------
async def test_edit_section_defaults_to_the_only_section():
    only = _section("Trees", description="Cover loss")
    dashboard = _dashboard(sections=[only])
    with (
        _get_dashboard(dashboard),
        patch(
            "src.api.repositories.dashboard_writer.update_section",
            new=AsyncMock(return_value=True),
        ) as update_section,
        bound_user_id("user-1"),
    ):
        command = await edit_dashboard_section.coroutine(
            title="Deforestation",
            state={"dashboard_id": str(dashboard.id)},
            tool_call_id="t1",
        )

    assert _status(command) == "success"
    kwargs = update_section.await_args.kwargs
    assert update_section.await_args.args == (only.id,)
    assert kwargs["title"] == "Deforestation"
    # An omitted description leaves the existing text alone.
    assert kwargs["description"] is dashboard_writer.UNSET


async def test_edit_section_by_title_is_case_insensitive():
    fires = _section("Fires", position=1)
    dashboard = _dashboard(sections=[_section("Deforestation"), fires])
    with (
        _get_dashboard(dashboard),
        patch(
            "src.api.repositories.dashboard_writer.update_section",
            new=AsyncMock(return_value=True),
        ) as update_section,
        bound_user_id("user-1"),
    ):
        command = await edit_dashboard_section.coroutine(
            section="fires",
            description="Burned area over time.",
            state={"dashboard_id": str(dashboard.id)},
            tool_call_id="t1",
        )

    assert _status(command) == "success"
    assert update_section.await_args.args == (fires.id,)
    assert (
        update_section.await_args.kwargs["description"]
        == "Burned area over time."
    )


async def test_edit_section_by_id():
    fires = _section("Fires", position=1)
    dashboard = _dashboard(sections=[_section("Deforestation"), fires])
    with (
        _get_dashboard(dashboard),
        patch(
            "src.api.repositories.dashboard_writer.update_section",
            new=AsyncMock(return_value=True),
        ) as update_section,
        bound_user_id("user-1"),
    ):
        command = await edit_dashboard_section.coroutine(
            section=str(fires.id),
            title="Fire activity",
            state={"dashboard_id": str(dashboard.id)},
            tool_call_id="t1",
        )
    assert _status(command) == "success"
    assert update_section.await_args.args == (fires.id,)


async def test_edit_section_lists_candidates_when_ambiguous():
    dashboard = _dashboard(
        sections=[_section("Deforestation"), _section("Fires", position=1)]
    )
    with _get_dashboard(dashboard), bound_user_id("user-1"):
        command = await edit_dashboard_section.coroutine(
            title="Renamed",
            state={"dashboard_id": str(dashboard.id)},
            tool_call_id="t1",
        )
    assert _status(command) == "error"
    content = _content(command)
    assert "Deforestation" in content and "Fires" in content


async def test_edit_section_with_no_sections_points_at_add():
    dashboard = _dashboard()
    with _get_dashboard(dashboard), bound_user_id("user-1"):
        command = await edit_dashboard_section.coroutine(
            title="Renamed",
            state={"dashboard_id": str(dashboard.id)},
            tool_call_id="t1",
        )
    assert _status(command) == "error"
    assert "add_dashboard_section" in _content(command)


async def test_edit_section_requires_something_to_change():
    dashboard = _dashboard(sections=[_section()])
    with _get_dashboard(dashboard), bound_user_id("user-1"):
        command = await edit_dashboard_section.coroutine(
            state={"dashboard_id": str(dashboard.id)}, tool_call_id="t1"
        )
    assert _status(command) == "error"
    assert "Nothing to change" in _content(command)


# ---------------------------------------------------------------------------
# Placing widgets in sections
# ---------------------------------------------------------------------------
async def test_add_to_dashboard_places_the_widget_in_a_named_section():
    section = _section("Deforestation")
    dashboard = _dashboard(sections=[section])
    insight = _insight()
    with (
        _get_dashboard(dashboard),
        patch(
            "src.agent.tools.add_to_dashboard._load_visible_insight",
            new=AsyncMock(return_value=insight),
        ),
        patch(
            "src.api.repositories.dashboard_writer.add_widget",
            new=AsyncMock(return_value="widget-1"),
        ) as add_widget,
        bound_user_id("user-1"),
    ):
        command = await add_to_dashboard.coroutine(
            section="deforestation",
            state={
                "insight_id": str(insight.id),
                "dashboard_id": str(dashboard.id),
            },
            tool_call_id="t1",
        )

    assert _status(command) == "success"
    add_widget.assert_awaited_once_with(
        str(dashboard.id),
        widget_type="insight",
        insight_id=str(insight.id),
        section_id=str(section.id),
    )
    assert "in section 'Deforestation'" in _content(command)


async def test_add_to_dashboard_rejects_an_unknown_section():
    dashboard = _dashboard(sections=[_section("Deforestation")])
    insight = _insight()
    with (
        _get_dashboard(dashboard),
        patch(
            "src.agent.tools.add_to_dashboard._load_visible_insight",
            new=AsyncMock(return_value=insight),
        ),
        patch(
            "src.api.repositories.dashboard_writer.add_widget",
            new=AsyncMock(),
        ) as add_widget,
        bound_user_id("user-1"),
    ):
        command = await add_to_dashboard.coroutine(
            section="Fires",
            state={
                "insight_id": str(insight.id),
                "dashboard_id": str(dashboard.id),
            },
            tool_call_id="t1",
        )

    assert _status(command) == "error"
    content = _content(command)
    assert "no section 'Fires'" in content
    assert "Deforestation" in content
    add_widget.assert_not_awaited()


# ---------------------------------------------------------------------------
# move_dashboard_widget
# ---------------------------------------------------------------------------
def _widget(dashboard, section_id=None, widget_type="text"):
    return SimpleNamespace(
        id=uuid4(),
        dashboard_id=dashboard.id,
        section_id=section_id,
        widget_type=widget_type,
        insight_id=None,
        position=0,
    )


def _get_widget(widget):
    return patch(
        "src.api.repositories.dashboard_writer.get_widget",
        new=AsyncMock(return_value=widget),
    )


async def test_move_widget_into_a_section_by_title():
    section = _section("Deforestation")
    dashboard = _dashboard(sections=[section])
    widget = _widget(dashboard)
    with (
        _get_dashboard(dashboard),
        _get_widget(widget),
        patch(
            "src.api.repositories.dashboard_writer.update_widget",
            new=AsyncMock(return_value=True),
        ) as update_widget,
        bound_user_id("user-1"),
    ):
        command = await move_dashboard_widget.coroutine(
            widget_id=str(widget.id),
            section="deforestation",
            state={},
            tool_call_id="t1",
        )

    assert _status(command) == "success"
    update_widget.assert_awaited_once_with(
        widget.id, position=None, section_id=str(section.id)
    )
    assert "section 'Deforestation'" in _content(command)


async def test_move_widget_out_to_the_top_level():
    section = _section("Deforestation")
    dashboard = _dashboard(sections=[section])
    widget = _widget(dashboard, section_id=section.id)
    with (
        _get_dashboard(dashboard),
        _get_widget(widget),
        patch(
            "src.api.repositories.dashboard_writer.update_widget",
            new=AsyncMock(return_value=True),
        ) as update_widget,
        bound_user_id("user-1"),
    ):
        command = await move_dashboard_widget.coroutine(
            widget_id=str(widget.id),
            ungroup=True,
            position=2,
            state={},
            tool_call_id="t1",
        )

    assert _status(command) == "success"
    update_widget.assert_awaited_once_with(
        widget.id, position=2, section_id=None
    )
    assert "ungrouped" in _content(command)


async def test_move_widget_requires_exactly_one_destination():
    section = _section("Deforestation")
    dashboard = _dashboard(sections=[section])
    widget = _widget(dashboard)
    for kwargs in ({}, {"section": "Deforestation", "ungroup": True}):
        with (
            _get_dashboard(dashboard),
            _get_widget(widget),
            bound_user_id("user-1"),
        ):
            command = await move_dashboard_widget.coroutine(
                widget_id=str(widget.id),
                state={},
                tool_call_id="t1",
                **kwargs,
            )
        assert _status(command) == "error"
        assert "exactly one" in _content(command)


async def test_move_widget_is_a_no_op_when_already_there():
    section = _section("Deforestation")
    dashboard = _dashboard(sections=[section])
    widget = _widget(dashboard, section_id=section.id)
    with (
        _get_dashboard(dashboard),
        _get_widget(widget),
        patch(
            "src.api.repositories.dashboard_writer.update_widget",
            new=AsyncMock(),
        ) as update_widget,
        bound_user_id("user-1"),
    ):
        command = await move_dashboard_widget.coroutine(
            widget_id=str(widget.id),
            section="Deforestation",
            state={},
            tool_call_id="t1",
        )
    assert _status(command) == "error"
    assert "already in section" in _content(command)
    update_widget.assert_not_awaited()

    with (
        _get_dashboard(dashboard),
        _get_widget(_widget(dashboard)),
        bound_user_id("user-1"),
    ):
        command = await move_dashboard_widget.coroutine(
            widget_id=str(uuid4()),
            ungroup=True,
            state={},
            tool_call_id="t1",
        )
    assert _status(command) == "error"
    assert "already ungrouped" in _content(command)


async def test_move_widget_unknown_id_errors():
    with (
        patch(
            "src.api.repositories.dashboard_writer.get_widget",
            new=AsyncMock(return_value=None),
        ),
        bound_user_id("user-1"),
    ):
        command = await move_dashboard_widget.coroutine(
            widget_id=str(uuid4()),
            ungroup=True,
            state={},
            tool_call_id="t1",
        )
    assert _status(command) == "error"
    assert "not found" in _content(command)


async def test_move_widget_on_someone_elses_dashboard_errors():
    dashboard = _dashboard(user_id="other-user", sections=[_section()])
    widget = _widget(dashboard, section_id=dashboard.sections[0].id)
    with (
        _get_dashboard(dashboard),
        _get_widget(widget),
        bound_user_id("user-1"),
    ):
        command = await move_dashboard_widget.coroutine(
            widget_id=str(widget.id),
            ungroup=True,
            state={},
            tool_call_id="t1",
        )
    assert _status(command) == "error"
    assert "not editable" in _content(command)


async def test_move_widget_rejects_an_unknown_section():
    dashboard = _dashboard(sections=[_section("Deforestation")])
    widget = _widget(dashboard)
    with (
        _get_dashboard(dashboard),
        _get_widget(widget),
        patch(
            "src.api.repositories.dashboard_writer.update_widget",
            new=AsyncMock(),
        ) as update_widget,
        bound_user_id("user-1"),
    ):
        command = await move_dashboard_widget.coroutine(
            widget_id=str(widget.id),
            section="Fires",
            state={},
            tool_call_id="t1",
        )
    assert _status(command) == "error"
    assert "no section 'Fires'" in _content(command)
    update_widget.assert_not_awaited()
