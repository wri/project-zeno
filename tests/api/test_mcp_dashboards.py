from datetime import date

import pytest

from src.agent.datasets.handlers.analytics_handler import INTEGRATED_ALERTS_ID
from src.api.data_models import InsightChartOrm, InsightOrm, UserOrm
from src.api.mcp.server import api_tools, build_server
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
PARANA = {
    "source": "gadm",
    "src_id": "BRA.16_1",
    "subtype": "state-province",
    "name": "Paraná",
}
PERU = {
    "source": "gadm",
    "src_id": "PER",
    "subtype": "country",
    "name": "Peru",
}


class FakeAlertsSource:
    async def area_ha_by_src_id(self, aois, start, end):
        area_ha = {PARA["src_id"]: 38463.65, PARANA["src_id"]: 131.05}
        return {aoi["src_id"]: area_ha[aoi["src_id"]] for aoi in aois}

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
    parana = await dashboard_writer.create_dashboard(
        user_id=OWNER, name="Paraná", aois=[PARANA]
    )
    await add_alerts_chart(parana, OWNER)
    await dashboard_writer.create_dashboard(
        user_id=OWNER, name="Peru", aois=[PERU]
    )
    await dashboard_writer.create_dashboard(
        user_id="someone-else", name="Not mine", aois=[PERU]
    )


async def call(user_id=OWNER) -> str:
    server = build_server(DashboardAlertsService(FakeAlertsSource()))
    with bound_user_id(user_id):
        async with api_tools(server) as tools:
            (tool,) = tools
            blocks = await tool.ainvoke({})
    return "\n".join(block["text"] for block in blocks)


async def test_exposes_the_alerts_summary():
    server = build_server(DashboardAlertsService(FakeAlertsSource()))
    async with api_tools(server) as tools:
        assert [tool.name for tool in tools] == ["summarize_dashboard_alerts"]


async def test_summary_covers_only_the_current_users_dashboards(dashboards):
    text = await call()

    assert "disturbance alerts" in text
    assert "2026-10-24 to 2026-10-30" in text
    assert "Not mine" not in text


async def test_summary_ranks_dashboards_by_area_and_gives_the_total(
    dashboards,
):
    text = await call()

    figures = [line for line in text.splitlines() if line.endswith(" ha")]
    assert figures == [
        "- Pará: 38,464 ha",
        "- Paraná: 131 ha",
        "Total: 38,595 ha",
    ]


async def test_summary_lists_untracked_dashboards_separately(dashboards):
    text = await call()

    not_tracked = next(
        line for line in text.splitlines() if "not tracked" in line.lower()
    )
    assert "Peru" in not_tracked


async def test_summary_requires_a_signed_in_user(dashboards):
    text = await call(user_id=None)

    assert "Pará" not in text
    assert "signed in" in text
