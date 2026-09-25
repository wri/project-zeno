"""Tests for the analysis template endpoints.

The analytics pull, the mosaic search and the text model are mocked. The
database writes are real.
"""

from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import delete, func, select

from src.agent.datasets.handlers.base import DataPullResult
from src.agent.imagery.base import ImageryProviderResult
from src.agent.models import ImageryState
from src.api.data_models import (
    DashboardAoiOrm,
    DashboardSectionOrm,
    InsightOrm,
)
from src.api.services.analysis_templates import builder
from src.api.services.analysis_templates.registry import NrtMonitoringArgs
from tests.api.test_dashboards import AUTH, _create_dashboard, _create_user
from tests.conftest import async_session_maker

ROWS = {
    "alert_date": ["2026-09-10", "2026-09-12"],
    "alert_confidence": ["high", "low"],
    "area_ha": [3.25, 0.5],
}


def _imagery_ok():
    return ImageryProviderResult(
        status="success",
        message="ok",
        imagery=ImageryState(
            tile_url="https://titiler/mosaic/{z}/{x}/{y}",
            mosaic_id="mosaic-1",
            target_date="2026-09-23",
            aoi_names=["Paraná"],
        ),
    )


@contextmanager
def _sources(pull_ok=True, imagery=None):
    pull = DataPullResult(
        success=pull_ok,
        data=ROWS if pull_ok else None,
        message="" if pull_ok else "analytics API unavailable",
    )
    with (
        patch.object(
            builder.AnalyticsHandler,
            "pull_data",
            AsyncMock(return_value=pull),
        ),
        patch.object(
            builder._IMAGERY_PROVIDER,
            "get_imagery",
            AsyncMock(return_value=imagery or _imagery_ok()),
        ),
        patch.object(
            builder,
            "generate_section_text",
            AsyncMock(
                return_value=("Recent alerts in Paraná", "3.3 ha of alerts.")
            ),
        ),
    ):
        yield


async def _apply(client, dashboard_id, **body):
    return await client.post(
        f"/api/dashboards/{dashboard_id}/sections/from-template",
        headers=AUTH,
        json={"template": "nrt-monitoring", **body},
    )


async def _count(model) -> int:
    async with async_session_maker() as session:
        return await session.scalar(select(func.count()).select_from(model))


# ---------------------------------------------------------------------------
# GET /api/analysis-templates
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_list_templates(client, auth_override):
    user = await _create_user("template-lister")
    auth_override(user.id)

    response = await client.get("/api/analysis-templates", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == [
        {
            "name": "nrt-monitoring",
            "label": "Near-real-time monitoring",
            "args_schema": NrtMonitoringArgs.model_json_schema(),
            "widgets": ["chart", "layer", "imagery"],
        }
    ]


@pytest.mark.asyncio
async def test_list_templates_requires_auth(client):
    response = await client.get("/api/analysis-templates")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/dashboards/{id}/sections/from-template
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_apply_template_builds_a_section(client, auth_override):
    user = await _create_user("template-owner")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)

    with _sources():
        response = await _apply(client, dashboard["id"], args={"days": 30})

    assert response.status_code == 201
    body = response.json()
    assert body["warnings"] == []
    assert len(body["widget_ids"]) == 3
    (section,) = body["dashboard"]["sections"]
    assert section["id"] == body["section_id"]
    assert section["title"] == "Recent alerts in Paraná"
    assert section["description"] == "3.3 ha of alerts."
    assert section["template"]["name"] == "nrt-monitoring"
    assert section["template"]["args"] == {"days": 30}

    widgets = body["dashboard"]["widgets"]
    assert [w["id"] for w in widgets] == body["widget_ids"]
    assert [w["widget_type"] for w in widgets] == ["insight", "map", "map"]
    assert all(w["section_id"] == body["section_id"] for w in widgets)
    insight = widgets[0]["insight"]
    assert insight["user_id"] == user.id
    assert insight["is_public"] is False
    assert insight["charts"][0]["x_axis"] == "alert_date"
    assert widgets[1]["config"]["dataset"]["dataset_id"] == 11
    assert widgets[2]["config"]["imagery"]["mosaic_id"] == "mosaic-1"


@pytest.mark.asyncio
async def test_apply_template_goes_after_the_last_section(
    client, auth_override
):
    user = await _create_user("template-after")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)
    await client.post(
        f"/api/dashboards/{dashboard['id']}/sections",
        headers=AUTH,
        json={"title": "Mine"},
    )

    with _sources():
        body = (await _apply(client, dashboard["id"])).json()

    sections = body["dashboard"]["sections"]
    assert [s["title"] for s in sections] == [
        "Mine",
        "Recent alerts in Paraná",
    ]
    assert sections[1]["position"] == 1
    assert sections[1]["template"]["args"] == {"days": 14}


@pytest.mark.asyncio
async def test_missing_imagery_is_a_warning(client, auth_override):
    user = await _create_user("template-no-imagery")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)
    no_imagery = ImageryProviderResult(
        status="error", message="No cloud-free imagery in the period."
    )

    with _sources(imagery=no_imagery):
        response = await _apply(client, dashboard["id"])

    assert response.status_code == 201
    body = response.json()
    assert body["warnings"] == ["No cloud-free imagery in the period."]
    assert len(body["widget_ids"]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"template": "no-such-template"},
        {"template": "nrt-monitoring", "args": {"days": 0}},
        {"template": "nrt-monitoring", "args": {"days": 366}},
        {"template": "nrt-monitoring", "args": {"window": 7}},
    ],
)
async def test_invalid_request_is_422(client, auth_override, body):
    user = await _create_user("template-422")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)

    response = await client.post(
        f"/api/dashboards/{dashboard['id']}/sections/from-template",
        headers=AUTH,
        json=body,
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_dashboard_without_area_is_422(client, auth_override):
    user = await _create_user("template-no-area")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)
    async with async_session_maker() as session:
        await session.execute(delete(DashboardAoiOrm))
        await session.commit()

    with _sources():
        response = await _apply(client, dashboard["id"])

    assert response.status_code == 422
    assert "no area" in response.json()["detail"]


@pytest.mark.asyncio
async def test_not_the_owner_is_404(client, auth_override):
    owner = await _create_user("template-real-owner")
    other = await _create_user("template-other")
    auth_override(owner.id)
    dashboard = await _create_dashboard(client)

    auth_override(other.id)
    with _sources():
        response = await _apply(client, dashboard["id"])

    assert response.status_code == 404
    assert await _count(DashboardSectionOrm) == 0


@pytest.mark.asyncio
async def test_failed_pull_is_502_and_writes_nothing(client, auth_override):
    user = await _create_user("template-502")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)

    with _sources(pull_ok=False):
        response = await _apply(client, dashboard["id"])

    assert response.status_code == 502
    assert "analytics API unavailable" in response.json()["detail"]
    assert await _count(DashboardSectionOrm) == 0
    assert await _count(InsightOrm) == 0


@pytest.mark.asyncio
async def test_public_dashboard_gets_public_insights(client, auth_override):
    user = await _create_user("template-public")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)
    await client.patch(
        f"/api/dashboards/{dashboard['id']}/public",
        headers=AUTH,
        json={"is_public": True},
    )

    with _sources():
        body = (await _apply(client, dashboard["id"])).json()

    assert body["dashboard"]["widgets"][0]["insight"]["is_public"] is True


@pytest.mark.asyncio
async def test_template_section_is_editable(client, auth_override):
    user = await _create_user("template-edit")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)
    with _sources():
        body = (await _apply(client, dashboard["id"])).json()
    section_id = body["section_id"]
    base = f"/api/dashboards/{dashboard['id']}"

    renamed = await client.patch(
        f"{base}/sections/{section_id}",
        headers=AUTH,
        json={"title": "My title"},
    )
    assert renamed.status_code == 200
    (section,) = renamed.json()["sections"]
    assert section["title"] == "My title"
    # The provenance record stays after an edit.
    assert section["template"]["name"] == "nrt-monitoring"

    moved = await client.patch(
        f"{base}/widgets/{body['widget_ids'][2]}",
        headers=AUTH,
        json={"section_id": None},
    )
    assert moved.status_code == 200
    imagery = next(
        w for w in moved.json()["widgets"] if w["id"] == body["widget_ids"][2]
    )
    assert imagery["section_id"] is None

    deleted = await client.delete(
        f"{base}/sections/{section_id}", headers=AUTH
    )
    assert deleted.status_code == 204
    after = (await client.get(base, headers=AUTH)).json()
    assert after["sections"] == []
    assert len(after["widgets"]) == 3
    assert all(w["section_id"] is None for w in after["widgets"])
    assert await _count(InsightOrm) == 1
