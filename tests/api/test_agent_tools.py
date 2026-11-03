from datetime import date

import pytest

from src.agent.datasets.handlers.analytics_handler import INTEGRATED_ALERTS_ID
from src.api.agent_tools import api_tools
from src.api.data_models import InsightChartOrm, InsightOrm, UserOrm
from src.api.repositories import dashboard_writer
from src.api.services.dashboard_alerts import DashboardAlertsService
from src.shared.request_context import bound_user_id
from tests.conftest import async_session_maker

pytestmark = pytest.mark.asyncio(loop_scope="session")

OWNER = "alerts-owner"

PARA = {
    "source": "gadm",
    "src_id": "BRA.14_1",
    "subtype": "state-province",
    "name": "Pará",
}
PERU = {
    "source": "gadm",
    "src_id": "PER",
    "subtype": "country",
    "name": "Peru",
}


class FakeAlertsSource:
    async def area_ha_by_src_id(self, aois, start, end):
        return {aoi["src_id"]: 38463.65 for aoi in aois}

    async def latest_alert_date(self):
        return date(2026, 10, 30)


async def create_user(user_id: str) -> None:
    async with async_session_maker() as session:
        session.add(
            UserOrm(id=user_id, name=user_id, email=f"{user_id}@example.com")
        )
        await session.commit()


async def add_alerts_chart(dashboard_id: str, user_id: str) -> None:
    async with async_session_maker() as session:
        insight = InsightOrm(
            user_id=user_id, thread_id="thread-1", insight_text="Alerts"
        )
        session.add(insight)
        await session.flush()
        session.add(
            InsightChartOrm(
                insight_id=insight.id,
                title="Integrated alerts",
                chart_type="line",
                chart_data=[],
                dataset_id=INTEGRATED_ALERTS_ID,
            )
        )
        await session.commit()
        insight_id = str(insight.id)
    await dashboard_writer.add_widget(
        dashboard_id, widget_type="insight", insight_id=insight_id
    )


@pytest.fixture
async def dashboards():
    await create_user(OWNER)
    await create_user("someone-else")
    para = await dashboard_writer.create_dashboard(
        user_id=OWNER, name="Pará", aois=[PARA]
    )
    await add_alerts_chart(para, OWNER)
    await dashboard_writer.create_dashboard(
        user_id=OWNER, name="Peru", aois=[PERU]
    )
    await dashboard_writer.create_dashboard(
        user_id="someone-else", name="Not mine", aois=[PERU]
    )


async def call(tool_name: str, user_id=OWNER, **args) -> str:
    service = DashboardAlertsService(FakeAlertsSource())
    with bound_user_id(user_id):
        async with api_tools(service) as tools:
            tool = {tool.name: tool for tool in tools}[tool_name]
            blocks = await tool.ainvoke(args)
    return "\n".join(block["text"] for block in blocks)


async def test_exposes_dashboard_list_and_alerts_summary():
    service = DashboardAlertsService(FakeAlertsSource())
    async with api_tools(service) as tools:
        assert {tool.name for tool in tools} == {
            "list_dashboards",
            "summarize_dashboard_alerts",
        }


async def test_lists_the_current_users_dashboards_and_alerts_tracking(
    dashboards,
):
    text = await call("list_dashboards")

    assert "Not mine" not in text
    para_line, peru_line = (
        next(line for line in text.splitlines() if line.startswith(f"- {n}"))
        for n in ("Pará", "Peru")
    )
    assert "tracks integrated disturbance alerts" in para_line
    assert "does not track" in peru_line


async def test_summary_names_dashboards_and_separates_untracked_ones(
    dashboards,
):
    text = await call("summarize_dashboard_alerts")

    assert "disturbance alerts" in text
    assert "2026-10-24 to 2026-10-30" in text
    assert "Pará: 38,464 ha" in text
    not_tracked = next(
        line for line in text.splitlines() if "not tracked" in line.lower()
    )
    assert "Peru" in not_tracked


async def test_tools_require_a_signed_in_user(dashboards):
    text = await call("list_dashboards", user_id=None)

    assert "Pará" not in text
    assert "signed in" in text
