"""Tests for the analyze endpoint: auth, validation and the synchronous cycle.

`POST /api/analyze` runs the analysis inside the request and returns the
generated insight. The analytics pull is faked; persistence goes through the
real `persist_insight` against the test database.
"""

import pytest
from sqlalchemy import select

from src.agent.subagents.analyst.charts import InsightChart
from src.api.app import app
from src.api.data_models import InsightOrm, UserOrm
from src.api.routers.analyze import CATALOG_DATASET_IDS, get_analysis_runner
from src.api.services.analysis_runner import AnalysisRunner
from src.api.services.analyze import AnalyzeResult
from tests.conftest import async_session_maker

VALID_DATASET_ID = sorted(CATALOG_DATASET_IDS)[0]

PAYLOAD = {
    "aois": [
        {"source": "gadm", "src_id": "CRI", "subtype": "country"},
    ],
    "dataset_id": VALID_DATASET_ID,
    "start_date": "2020-01-01",
    "end_date": "2020-12-31",
}

CHARTS = [
    InsightChart(
        position=0,
        title="Annual Tree Cover Loss",
        chart_type="bar",
        x_axis="tree_cover_loss_year",
        y_axis="area_ha",
        chart_data=[{"tree_cover_loss_year": 2020, "area_ha": 1000.0}],
    )
]


class _Result:
    def __init__(self, success, message=""):
        self.success = success
        self.message = message


class FakeAnalyzeService:
    def __init__(self, *, success: bool = True):
        self._success = success

    async def analyze(self, aois, dataset_id, start_date, end_date):
        return AnalyzeResult(
            data=_Result(self._success, "upstream error"),
            charts=CHARTS if self._success else [],
        )


@pytest.fixture
def runner_override():
    """Swap the analytics pull for a fake; keep the real insight persistence."""

    def _override(*, success: bool = True):
        app.dependency_overrides[get_analysis_runner] = lambda: (
            AnalysisRunner(FakeAnalyzeService(success=success))
        )

    yield _override
    app.dependency_overrides.pop(get_analysis_runner, None)


async def _create_user(user_id: str) -> UserOrm:
    async with async_session_maker() as session:
        user = UserOrm(
            id=user_id,
            name=user_id,
            email=f"{user_id}@example.com",
        )
        session.add(user)
        await session.commit()
        return user


async def _insight_count(user_id: str) -> int:
    async with async_session_maker() as session:
        result = await session.execute(
            select(InsightOrm).where(InsightOrm.user_id == user_id)
        )
        return len(result.scalars().all())


async def test_analyze_requires_auth(client):
    response = await client.post("/api/analyze", json=PAYLOAD)
    assert response.status_code == 401


async def test_analyze_rejects_unknown_dataset_id(client, auth_override):
    await _create_user("user-analyze")
    auth_override("user-analyze")

    response = await client.post(
        "/api/analyze",
        json={**PAYLOAD, "dataset_id": 999},
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 422
    assert "Unknown dataset_id" in response.json()["detail"]


async def test_analyze_returns_persisted_insight(
    client, auth_override, runner_override
):
    await _create_user("user-analyze")
    auth_override("user-analyze")
    runner_override(success=True)

    response = await client.post(
        "/api/analyze",
        json={**PAYLOAD, "thread_id": "t-1"},
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["thread_id"] == "t-1"
    # Charts only, no narrative: this path doesn't run the LLM text step.
    assert body["insight_text"] == ""
    assert len(body["charts"]) == 1
    assert body["charts"][0]["title"] == "Annual Tree Cover Loss"


async def test_analyze_insight_is_retrievable(
    client, auth_override, runner_override
):
    """The response is the same resource `GET /api/insights/{id}` serves."""
    await _create_user("user-analyze")
    auth_override("user-analyze")
    runner_override(success=True)

    created = (
        await client.post(
            "/api/analyze",
            json=PAYLOAD,
            headers={"Authorization": "Bearer token"},
        )
    ).json()

    response = await client.get(
        f"/api/insights/{created['id']}",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == created["id"]
    assert [c["title"] for c in body["charts"]] == [
        c["title"] for c in created["charts"]
    ]


async def test_analyze_upstream_failure_returns_502_and_persists_nothing(
    client, auth_override, runner_override
):
    await _create_user("user-analyze")
    auth_override("user-analyze")
    runner_override(success=False)

    response = await client.post(
        "/api/analyze",
        json=PAYLOAD,
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Analysis failed"
    assert await _insight_count("user-analyze") == 0
