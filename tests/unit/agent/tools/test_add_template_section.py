"""Tests for the add_template_section agent tool, with apply_template mocked."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.agent.tools import add_template_section as tool_module
from src.agent.tools.add_template_section import SPEC, add_template_section
from src.api.services.analysis_templates.builder import (
    TemplateResult,
    WidgetFailedError,
)
from src.shared.request_context import bound_user_id


def _dashboard(user_id="user-1"):
    return SimpleNamespace(
        id=uuid4(), user_id=user_id, name="Paraná", is_public=False
    )


def _result(warnings=()):
    return TemplateResult(
        section_id="section-1",
        widget_ids=["w1", "w2"],
        title="Recent alerts in Paraná",
        description="3.3 ha of alerts.",
        warnings=list(warnings),
    )


@contextmanager
def _patched(dashboard, apply=None):
    apply = apply or AsyncMock(return_value=_result())
    with (
        patch(
            "src.api.repositories.dashboard_writer.get_dashboard",
            new=AsyncMock(return_value=dashboard),
        ),
        patch.object(tool_module, "apply_template", apply),
        bound_user_id("user-1"),
    ):
        yield apply


async def _call(state=None, **kwargs):
    return await add_template_section.coroutine(
        template=kwargs.pop("template", "nrt-monitoring"),
        state=state or {},
        tool_call_id="t1",
        **kwargs,
    )


def _message(command):
    return command.update["messages"][0]


@pytest.mark.asyncio
async def test_applies_the_template_and_reloads_the_dashboard():
    dashboard = _dashboard()
    with _patched(dashboard) as apply:
        command = await _call(
            state={"dashboard_id": str(dashboard.id), "language": "es"},
            template_args={"days": 30},
        )

    message = _message(command)
    assert message.status == "success"
    assert message.response_metadata["msg_type"] == "dashboard_updated"
    assert command.update["dashboard_id"] == str(dashboard.id)
    assert "Recent alerts in Paraná" in message.content
    assert "section-1" in message.content
    assert "2 widgets" in message.content
    assert "3.3 ha of alerts." in message.content
    args = apply.await_args.args
    assert args[0] is dashboard
    assert args[1].name == "nrt-monitoring"
    assert args[2].days == 30
    assert args[3:] == ("user-1", "es")


@pytest.mark.asyncio
async def test_warnings_are_in_the_reply():
    dashboard = _dashboard()
    apply = AsyncMock(return_value=_result(["No cloud-free imagery."]))
    with _patched(dashboard, apply):
        command = await _call(state={"dashboard_id": str(dashboard.id)})

    assert "Warning: No cloud-free imagery." in _message(command).content


@pytest.mark.asyncio
async def test_falls_back_to_the_dashboard_on_screen():
    dashboard = _dashboard()
    with _patched(dashboard) as apply:
        await _call(
            state={"view_context": {"dashboard_id": str(dashboard.id)}}
        )

    apply.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_dashboard_is_an_error():
    with _patched(None) as apply:
        command = await _call()

    assert _message(command).status == "error"
    assert "create_dashboard" in _message(command).content
    apply.assert_not_awaited()


@pytest.mark.asyncio
async def test_not_the_owner_is_an_error():
    dashboard = _dashboard(user_id="someone-else")
    with _patched(dashboard) as apply:
        command = await _call(state={"dashboard_id": str(dashboard.id)})

    assert _message(command).status == "error"
    assert "not found or not editable" in _message(command).content
    apply.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "args, problem",
    [
        ({"days": 0}, "days: Input should be greater than or equal to 1"),
        ({"days": 366}, "days: Input should be less than or equal to 365"),
        ({"window": 7}, "window: Extra inputs are not permitted"),
    ],
)
async def test_invalid_args_are_an_error(args, problem):
    dashboard = _dashboard()
    with _patched(dashboard) as apply:
        command = await _call(
            state={"dashboard_id": str(dashboard.id)}, template_args=args
        )

    assert _message(command).status == "error"
    assert problem in _message(command).content
    assert "days (integer, >=1, <=365, default 14)" in (
        _message(command).content
    )
    apply.assert_not_awaited()


@pytest.mark.asyncio
async def test_template_error_becomes_an_error_message():
    dashboard = _dashboard()
    apply = AsyncMock(side_effect=WidgetFailedError("analytics API down"))
    with _patched(dashboard, apply):
        command = await _call(state={"dashboard_id": str(dashboard.id)})

    assert _message(command).status == "error"
    assert "analytics API down" in _message(command).content


def test_schema_lists_the_template_names():
    prop = add_template_section.args_schema.model_json_schema()["properties"][
        "template"
    ]
    # One name renders as `const`, several as `enum`.
    assert prop.get("enum", [prop.get("const")]) == ["nrt-monitoring"]


def test_prompt_fragment_lists_each_template():
    assert "'nrt-monitoring'" in SPEC.prompt_fragment
    assert (
        "Args: days (integer, >=1, <=365, default 14): Length of the period"
        in SPEC.prompt_fragment
    )


def test_schema_is_valid_for_gemini():
    # A parameter named `args` becomes `v__args`, an array without `items`,
    # which the Gemini API rejects with a 400.
    from langchain_google_genai._function_utils import (
        convert_to_genai_function_declarations,
    )

    properties = add_template_section.args_schema.model_json_schema()[
        "properties"
    ]
    assert "template_args" in properties
    assert not any(name.startswith("v__") for name in properties)

    tools = convert_to_genai_function_declarations([add_template_section])
    declaration = tools[0].function_declarations[0]
    for name, schema in declaration.parameters.properties.items():
        assert schema.type != "ARRAY" or schema.items is not None, name
