"""The generic agent tools over the analysis templates.

Three things matter here and none belongs to any one template.

**Dispatch.** The tools look a template up in the registry, hand it its own
validated parameters and report what it returned, so a new template needs no
change in this layer. Nothing here names a parameter: `params` is a dict the
template's own model validates, which is what lets a template that is not
driven by a date range use the same tools.

**The two rebuild verbs are different asks.** `refresh` re-runs a section
with the parameters it already has — the same question, asked again now —
and takes none. `reconfigure` asks a different question, and the previous
answer is deleted.

**The nudge before a reconfigure is a rule, not an instruction.** A prompt
asking the model to check first is a hope where a refusal is a guarantee.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.agent.tools.analysis_sections import (
    add_analysis_section,
    reconfigure_analysis_section,
    refresh_analysis_section,
)
from src.api.services.analysis_templates.base import (
    AlreadyBuiltError,
    DataUnavailableError,
    TemplateResult,
)
from src.shared.request_context import bound_user_id

TEMPLATE = "nrt-monitoring"


def _section(title="Recent disturbance", type=TEMPLATE, **config):
    return SimpleNamespace(
        id=uuid4(),
        title=title,
        type=type,
        config=config
        or {
            "template": TEMPLATE,
            "params": {"days": 14},
            "start_date": "2026-08-20",
            "end_date": "2026-09-03",
        },
    )


def _dashboard(*sections, aois=True):
    return SimpleNamespace(
        id=uuid4(),
        name="Genève",
        sections=list(sections),
        aois=[
            SimpleNamespace(
                source="gadm",
                src_id="CHE.8_1",
                subtype="state-province",
                name="Genève",
            )
        ]
        if aois
        else [],
    )


def _result(**kwargs):
    return TemplateResult(
        **{
            "template": TEMPLATE,
            "section_id": "sec-1",
            "widget_ids": ["w1", "w2", "w3"],
            "summary": "a monitoring section covering 2026-06-05 to 2026-09-03",
            "warnings": [],
            **kwargs,
        }
    )


def _content(command):
    (message,) = command.update["messages"]
    return message.content


def _fake_template(**methods):
    """A stand-in template with the real one's parameter model."""
    from src.api.services.analysis_templates.nrt_monitoring import NrtParams
    from src.api.services.analysis_templates.registry import ENTRIES_BY_NAME

    return SimpleNamespace(
        entry=ENTRIES_BY_NAME[TEMPLATE],
        params_model=NrtParams,
        build=methods.get("build", AsyncMock(return_value=_result())),
        refresh=methods.get("refresh", AsyncMock(return_value=_result())),
        describe=methods.get(
            "describe", lambda section: "2026-08-20 to 2026-09-03"
        ),
    )


async def _add(dashboard, template=None, **kwargs):
    kwargs.setdefault("template", TEMPLATE)
    kwargs.setdefault("state", {"dashboard_id": str(dashboard.id)})
    recipe = template if template is not None else _fake_template()
    with (
        patch(
            "src.agent.tools.analysis_sections.load_editable_dashboard",
            AsyncMock(return_value=dashboard),
        ),
        patch(
            "src.agent.tools.analysis_sections.registry.get_template",
            return_value=recipe,
        ),
        bound_user_id("user-1"),
    ):
        # .coroutine bypasses the injected-argument plumbing, as the other
        # dashboard tool tests do.
        command = await add_analysis_section.coroutine(
            **kwargs, tool_call_id="call-1"
        )
    return command, recipe


async def _rebuild(tool, dashboard, template=None, **kwargs):
    kwargs.setdefault("state", {"dashboard_id": str(dashboard.id)})
    recipe = template if template is not None else _fake_template()
    with (
        patch(
            "src.agent.tools.analysis_sections.load_editable_dashboard",
            AsyncMock(return_value=dashboard),
        ),
        patch(
            "src.agent.tools.analysis_sections.registry.get_template",
            return_value=recipe,
        ),
        bound_user_id("user-1"),
    ):
        command = await tool.coroutine(**kwargs, tool_call_id="call-1")
    return command, recipe


async def _refresh(dashboard, template=None, **kwargs):
    return await _rebuild(
        refresh_analysis_section, dashboard, template, **kwargs
    )


async def _reconfigure(dashboard, template=None, **kwargs):
    kwargs.setdefault("params", {"days": 90})
    return await _rebuild(
        reconfigure_analysis_section, dashboard, template, **kwargs
    )


# --- add: dispatch ----------------------------------------------------------


@pytest.mark.asyncio
async def test_build_dispatches_to_the_named_template():
    dashboard = _dashboard()

    command, recipe = await _add(dashboard, params={"days": 30})

    recipe.build.assert_awaited_once()
    assert recipe.build.await_args.kwargs["params"].days == 30
    assert recipe.build.await_args.args[0] is dashboard
    # The tool reports the template's own words, not its own.
    assert "a monitoring section covering" in _content(command)
    assert command.update["dashboard_id"] == str(dashboard.id)


@pytest.mark.asyncio
async def test_omitted_parameters_use_the_templates_own_defaults():
    dashboard = _dashboard()

    _, recipe = await _add(dashboard)

    assert recipe.build.await_args.kwargs["params"].days == 14


@pytest.mark.asyncio
async def test_unknown_template_names_the_known_ones():
    """The registry's own error reaches the model unchanged, so it can
    retry with a name that exists."""
    dashboard = _dashboard()
    with (
        patch(
            "src.agent.tools.analysis_sections.load_editable_dashboard",
            AsyncMock(return_value=dashboard),
        ),
        bound_user_id("user-1"),
    ):
        command = await add_analysis_section.coroutine(
            template="no-such-template",
            state={"dashboard_id": str(dashboard.id)},
            tool_call_id="call-1",
        )

    body = _content(command)
    assert "no-such-template" in body
    assert TEMPLATE in body


@pytest.mark.asyncio
async def test_a_parameter_the_template_does_not_take_is_refused():
    """`extra="forbid"` on the model: nothing here knows what a parameter
    means, so the template's own refusal is what the model sees."""
    dashboard = _dashboard()

    command, recipe = await _add(dashboard, params={"threshold": 30})

    recipe.build.assert_not_called()
    assert "does not fit" in _content(command)


@pytest.mark.asyncio
async def test_out_of_range_parameter_is_refused_before_the_build():
    dashboard = _dashboard()

    command, recipe = await _add(dashboard, params={"days": 400})

    recipe.build.assert_not_called()
    body = _content(command)
    assert "`days` does not fit" in body
    # The refusal lists what the template does take, so the model retries
    # rather than guessing again.
    assert "max 365" in body


@pytest.mark.asyncio
async def test_already_built_tells_the_model_not_to_build_a_second():
    dashboard = _dashboard(_section())
    recipe = _fake_template(
        build=AsyncMock(
            side_effect=AlreadyBuiltError(
                "Dashboard 'Genève' already has the monitoring section "
                "'Recent disturbance' for 2026-08-20 to 2026-09-03.",
                "sec-1",
            )
        )
    )

    command, _ = await _add(dashboard, template=recipe)

    body = _content(command)
    assert "already has" in body
    assert "rather than building a second one" in body
    assert "refresh_analysis_section" in body


@pytest.mark.asyncio
async def test_a_template_failure_is_reported_in_its_own_words():
    dashboard = _dashboard()
    recipe = _fake_template(
        build=AsyncMock(
            side_effect=DataUnavailableError(
                "Could not retrieve alert data for 'Genève': upstream 503"
            )
        )
    )

    command, _ = await _add(dashboard, template=recipe)

    assert "upstream 503" in _content(command)


@pytest.mark.asyncio
async def test_warnings_are_passed_on_rather_than_swallowed():
    dashboard = _dashboard()
    recipe = _fake_template(
        build=AsyncMock(
            return_value=_result(
                widget_ids=["w1", "w2"],
                warnings=["The area is too large for satellite imagery."],
            )
        )
    )

    command, _ = await _add(dashboard, template=recipe)

    assert "too large for satellite imagery" in _content(command)


@pytest.mark.asyncio
async def test_build_without_a_dashboard_says_how_to_get_one():
    command, recipe = await _add(_dashboard(), state={})

    recipe.build.assert_not_called()
    assert "create_dashboard" in _content(command)


# --- refresh: same question, asked again now --------------------------------


@pytest.mark.asyncio
async def test_refresh_reuses_the_parameters_the_section_was_built_with():
    """It takes none: the section records what it was built with.

    Built with 30 days, not the template's default of 14, so a refresh that
    quietly fell back to the default would fail here.
    """
    dashboard = _dashboard(
        _section(
            template=TEMPLATE,
            params={"days": 30},
            start_date="2026-08-04",
            end_date="2026-09-03",
        )
    )

    command, recipe = await _refresh(dashboard)

    recipe.refresh.assert_awaited_once()
    assert recipe.refresh.await_args.kwargs["params"].days == 30
    assert command.update["dashboard_id"] == str(dashboard.id)


@pytest.mark.asyncio
async def test_refresh_needs_no_confirmation():
    """The user asked for exactly this, and what the section covers does
    not change — so there is nothing to agree to."""
    dashboard = _dashboard(_section())

    _, recipe = await _refresh(dashboard)

    recipe.refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_refresh_of_a_section_with_no_recorded_parameters():
    """A section written before a parameter existed falls back to the
    template's default rather than failing."""
    dashboard = _dashboard(_section(template=TEMPLATE))

    _, recipe = await _refresh(dashboard)

    assert recipe.refresh.await_args.kwargs["params"].days == 14


# --- reconfigure: a different question, so it is confirmed ------------------


@pytest.mark.asyncio
async def test_unconfirmed_change_does_nothing_and_asks():
    dashboard = _dashboard(_section())

    command, recipe = await _reconfigure(dashboard)

    recipe.refresh.assert_not_called()
    body = _content(command)
    assert "send_nudge" in body
    # It states what is on screen now, in the template's own words, so the
    # model can offer real options.
    assert "2026-08-20 to 2026-09-03" in body
    # And what the change costs, which the template's registry entry says.
    assert "previous ones are deleted" in body


@pytest.mark.asyncio
async def test_confirmed_change_applies():
    dashboard = _dashboard(_section())

    command, recipe = await _reconfigure(dashboard, confirmed=True)

    recipe.refresh.assert_awaited_once()
    assert recipe.refresh.await_args.kwargs["params"].days == 90
    assert "2026-06-05" in _content(command)
    assert command.update["dashboard_id"] == str(dashboard.id)


@pytest.mark.asyncio
async def test_out_of_range_parameter_refused_before_anything_else():
    dashboard = _dashboard(_section())

    command, recipe = await _reconfigure(
        dashboard, params={"days": 400}, confirmed=True
    )

    recipe.refresh.assert_not_called()
    assert "does not fit" in _content(command)


# --- both rebuild verbs share how they find a section -----------------------


@pytest.mark.asyncio
async def test_two_templated_sections_must_be_named():
    dashboard = _dashboard(
        _section(title="Alerts, August"), _section(title="Alerts, July")
    )

    command, recipe = await _reconfigure(dashboard, confirmed=True)

    recipe.refresh.assert_not_called()
    body = _content(command)
    assert "more than one curated section" in body
    assert "Alerts, August" in body and "Alerts, July" in body


@pytest.mark.asyncio
async def test_a_named_section_is_dispatched_on_its_own_type():
    """The rebuild runs whichever template built the section, not a
    caller-named one."""
    august = _section(title="Alerts, August")
    dashboard = _dashboard(august, _section(title="Alerts, July"))

    command, recipe = await _refresh(dashboard, section="Alerts, August")

    recipe.refresh.assert_awaited_once()
    assert recipe.refresh.await_args.args[0] is august


@pytest.mark.asyncio
async def test_dashboard_without_a_templated_section():
    dashboard = _dashboard(_section(type="default"))

    command, recipe = await _refresh(dashboard)

    recipe.refresh.assert_not_called()
    assert "add_analysis_section" in _content(command)
