"""Live routing test: a monitoring request goes to add_template_section.

The model runs for real (experimental profile). The dashboard load and the
template build are mocked, so the test needs no database and no data APIs.
Run it on its own; it calls the LLM.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.agent.graph import fetch_zeno
from src.agent.tools import add_template_section as tool_module
from src.api.services.analysis_templates.builder import TemplateResult

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture(scope="function", autouse=True)
def test_db():
    """No database for this test."""


@pytest.fixture(scope="function", autouse=True)
def test_db_session():
    """No database for this test."""


@pytest.fixture(scope="function", autouse=True)
def test_db_pool():
    """No database pool for this test."""


def _dashboard():
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id="test-user-123",
        name="Paraná",
        description=None,
        is_public=False,
        aois=[
            SimpleNamespace(
                source="gadm",
                src_id="BRA.16_1",
                subtype="state-province",
                name="Paraná",
                position=0,
            )
        ],
        sections=[],
        widgets=[],
    )


def _tool_calls(steps):
    return [
        call
        for step in steps
        for value in step.values()
        for message in (value or {}).get("messages", [])
        for call in getattr(message, "tool_calls", None) or []
    ]


async def test_monitoring_request_uses_the_template(structlog_context):
    dashboard = _dashboard()
    apply = AsyncMock(
        return_value=TemplateResult(
            section_id=str(uuid.uuid4()),
            widget_ids=["w1", "w2", "w3"],
            title="Recent disturbance alerts in Paraná",
            description="12 ha of alerts in the last 14 days.",
        )
    )
    agent = await fetch_zeno(
        ff="experimental", checkpointer=None, page="dashboard"
    )

    steps = []
    with (
        patch(
            "src.api.repositories.dashboard_writer.get_dashboard",
            new=AsyncMock(return_value=dashboard),
        ),
        patch.object(tool_module, "apply_template", apply),
    ):
        async for step in agent.astream(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Monitor deforestation in Paraná on my dashboard."
                        ),
                    }
                ],
                "view_context": {
                    "page": "dashboard",
                    "dashboard_id": str(dashboard.id),
                },
            },
            {"configurable": {"thread_id": str(uuid.uuid4())}},
        ):
            steps.append(step)

    calls = [
        c for c in _tool_calls(steps) if c["name"] == "add_template_section"
    ]
    assert calls, [c["name"] for c in _tool_calls(steps)]
    assert calls[0]["args"]["template"] == "nrt-monitoring"
    apply.assert_awaited()
