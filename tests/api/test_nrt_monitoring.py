"""Tests for the near-real-time monitoring section endpoint.

The endpoint composes three slow things — an analytics pull, a mosaic build
and a model call — so every test here stands them in. What is under test is
the composition: what the section contains, what happens when a part fails,
and that a second click does not build a second section.
"""

from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from src.agent.datasets.handlers.analytics_handler import INTEGRATED_ALERTS_ID
from src.agent.datasets.handlers.base import DataPullResult
from src.agent.imagery.base import ImageryProviderResult
from src.agent.models import ImageryState
from src.api.data_models import UserOrm
from src.api.services.nrt_summary import SectionSummary
from tests.conftest import async_session_maker

PARANA = {
    "source": "gadm",
    "src_id": "BRA.16_1",
    "subtype": "state-province",
    "name": "Paraná",
}
AUTH = {"Authorization": "Bearer t"}
ENDPOINT = "/api/dashboards/{id}/sections/nrt-monitoring"

# Column-oriented, the shape the analytics API returns.
ALERT_DATA = {
    "alert_date": ["2026-08-30", "2026-08-31", "2026-09-01"],
    "alert_confidence": ["high", "highest", "high"],
    "area_ha": [12.5, 30.0, 8.0],
    "aoi_id": ["BRA.16_1", "BRA.16_1", "BRA.16_1"],
}

IMAGERY = ImageryState(
    provider="sentinel-2",
    tile_url="https://tiles.globalforestwatch.org/cog/mosaic/tiles/WebMercatorQuad/{z}/{x}/{y}.png?url=s3",
    tilejson_url="https://tiles.globalforestwatch.org/cog/mosaic/WebMercatorQuad/tilejson.json?url=s3",
    mosaic_id="token-1",
    item_count=8,
    target_date="2026-09-02",
    window_days=7,
    max_cloud_cover=20,
    aoi_names=["Paraná"],
)

SUMMARY = SectionSummary(
    title="Alerts in Paraná, last 90 days",
    description="50.5 ha of alerts, mostly high confidence.",
)


async def _create_user(user_id: str) -> UserOrm:
    """A real user row, so two identities in one test do not collide on the
    single email the auth override hands out."""
    async with async_session_maker() as session:
        user = UserOrm(
            id=user_id, name=user_id, email=f"{user_id}@example.com"
        )
        session.add(user)
        await session.commit()
        return user


async def _create_dashboard(client, aois=None) -> dict:
    response = await client.post(
        "/api/dashboards", headers=AUTH, json={"aois": aois or [PARANA]}
    )
    assert response.status_code == 201
    return response.json()


def _patches(
    *,
    pull_success: bool = True,
    imagery: ImageryProviderResult | None = None,
    imagery_spy: dict | None = None,
):
    """Stand in for the three slow collaborators of the recipe.

    The pull stand-in **mutates its ``aois`` argument** exactly as the real
    ``AnalyticsHandler`` does (it strips the GADM level suffix in place), so
    a builder that shares one AOI dict between the data pull and the imagery
    lookup fails here rather than only in production.
    """
    pull = DataPullResult(
        success=pull_success,
        data=ALERT_DATA if pull_success else None,
        message="ok" if pull_success else "analytics api unavailable",
        data_points_count=3,
        analytics_api_url="https://api.example/analytics/1",
    )

    async def _pull_data(*_args, aois, **_kwargs):
        for entry in aois:
            if entry["src_id"][-2:] in ("_1", "_2", "_3", "_4", "_5"):
                entry["src_id"] = entry["src_id"][:-2]
        return pull

    async def _get_imagery(request):
        if imagery_spy is not None:
            imagery_spy["src_id"] = request.aois[0]["src_id"]
        return imagery or ImageryProviderResult(
            status="success", message="built", imagery=IMAGERY
        )

    return (
        patch(
            "src.agent.datasets.handlers.analytics_handler.AnalyticsHandler.pull_data",
            _pull_data,
        ),
        patch(
            "src.api.services.nrt_monitoring._IMAGERY_PROVIDER.get_imagery",
            _get_imagery,
        ),
        patch(
            "src.api.services.nrt_monitoring.generate_section_summary",
            AsyncMock(return_value=SUMMARY),
        ),
    )


@pytest.mark.asyncio
async def test_builds_a_sealed_section_with_three_widgets(
    client, auth_override
):
    auth_override("nrt-owner")
    dashboard = await _create_dashboard(client)

    pull, imagery, summary = _patches()
    with pull, imagery, summary:
        response = await client.post(
            ENDPOINT.format(id=dashboard["id"]), headers=AUTH, json={}
        )

    assert response.status_code == 201
    body = response.json()
    assert body["created"] is True
    assert body["warnings"] == []

    (section,) = body["sections"]
    assert section["type"] == "nrt-monitoring"
    assert section["title"] == SUMMARY.title
    assert section["description"] == SUMMARY.description
    assert section["id"] == body["section_id"]

    widgets = sorted(body["widgets"], key=lambda w: w["position"])
    assert [w["widget_type"] for w in widgets] == ["insight", "map", "map"]
    assert all(w["section_id"] == section["id"] for w in widgets)

    # The chart insight is expanded, and carries the deterministic line chart.
    (chart,) = widgets[0]["insight"]["charts"]
    assert chart["chart_type"] == "line"
    assert chart["color_field"] == "alert_confidence"

    # The alerts layer covers the same period the chart does.
    alerts = widgets[1]["config"]["dataset"]
    assert alerts["dataset_id"] == INTEGRATED_ALERTS_ID
    assert f"start_date={alerts['start_date']}" in alerts["tile_url"]
    assert alerts["end_date"] == date.today().isoformat()

    assert widgets[2]["config"]["imagery"]["mosaic_id"] == "token-1"


@pytest.mark.asyncio
async def test_imagery_failure_still_builds_the_section(client, auth_override):
    auth_override("nrt-no-imagery")
    dashboard = await _create_dashboard(client)

    pull, imagery, summary = _patches(
        imagery=ImageryProviderResult(
            status="error", message="AOI is too large for mosaics."
        )
    )
    with pull, imagery, summary:
        response = await client.post(
            ENDPOINT.format(id=dashboard["id"]), headers=AUTH, json={}
        )

    assert response.status_code == 201
    body = response.json()
    assert body["warnings"] == ["AOI is too large for mosaics."]
    assert [w["widget_type"] for w in body["widgets"]] == ["insight", "map"]
    assert len(body["sections"]) == 1


@pytest.mark.asyncio
async def test_analytics_failure_builds_nothing(client, auth_override):
    auth_override("nrt-no-data")
    dashboard = await _create_dashboard(client)

    pull, imagery, summary = _patches(pull_success=False)
    with pull, imagery, summary:
        response = await client.post(
            ENDPOINT.format(id=dashboard["id"]), headers=AUTH, json={}
        )

    assert response.status_code == 502
    body = (
        await client.get(f"/api/dashboards/{dashboard['id']}", headers=AUTH)
    ).json()
    assert body["sections"] == []
    assert body["widgets"] == []


@pytest.mark.asyncio
async def test_second_call_returns_the_existing_section(client, auth_override):
    auth_override("nrt-twice")
    dashboard = await _create_dashboard(client)

    pull, imagery, summary = _patches()
    with pull, imagery, summary:
        first = await client.post(
            ENDPOINT.format(id=dashboard["id"]), headers=AUTH, json={}
        )
        second = await client.post(
            ENDPOINT.format(id=dashboard["id"]), headers=AUTH, json={}
        )

    assert second.status_code == 201
    assert second.json()["created"] is False
    assert second.json()["section_id"] == first.json()["section_id"]
    assert len(second.json()["sections"]) == 1


@pytest.mark.asyncio
async def test_force_builds_a_second_section(client, auth_override):
    auth_override("nrt-force")
    dashboard = await _create_dashboard(client)

    pull, imagery, summary = _patches()
    with pull, imagery, summary:
        await client.post(
            ENDPOINT.format(id=dashboard["id"]), headers=AUTH, json={}
        )
        second = await client.post(
            ENDPOINT.format(id=dashboard["id"]),
            headers=AUTH,
            json={"force": True},
        )

    assert second.json()["created"] is True
    assert len(second.json()["sections"]) == 2


@pytest.mark.asyncio
async def test_supplied_title_and_description_win(client, auth_override):
    auth_override("nrt-titled")
    dashboard = await _create_dashboard(client)

    pull, imagery, summary = _patches()
    with pull, imagery, summary:
        response = await client.post(
            ENDPOINT.format(id=dashboard["id"]),
            headers=AUTH,
            json={"title": "My watch", "description": "My words."},
        )

    (section,) = response.json()["sections"]
    assert section["title"] == "My watch"
    assert section["description"] == "My words."


@pytest.mark.asyncio
async def test_days_out_of_range_rejected(client, auth_override):
    auth_override("nrt-bad-days")
    dashboard = await _create_dashboard(client)

    response = await client.post(
        ENDPOINT.format(id=dashboard["id"]), headers=AUTH, json={"days": 999}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_other_users_dashboard_returns_404(client, auth_override):
    owner = await _create_user("nrt-owner-2")
    stranger = await _create_user("nrt-stranger")
    auth_override(owner.id)
    dashboard = await _create_dashboard(client)

    auth_override(stranger.id)
    response = await client.post(
        ENDPOINT.format(id=dashboard["id"]), headers=AUTH, json={}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_requires_auth(client):
    response = await client.post(
        ENDPOINT.format(id="00000000-0000-0000-0000-000000000000"), json={}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_imagery_gets_the_canonical_aoi_id(client, auth_override):
    """The data pull rewrites its input in place — the analytics API wants a
    GADM id without the level suffix. The imagery lookup that follows must
    still see the id the dashboard stored, or it resolves no geometry and the
    section silently loses its satellite widget."""
    auth_override("nrt-aoi-id")
    dashboard = await _create_dashboard(client)
    seen: dict = {}

    pull, imagery, summary = _patches(imagery_spy=seen)
    with pull, imagery, summary:
        response = await client.post(
            ENDPOINT.format(id=dashboard["id"]), headers=AUTH, json={}
        )

    assert response.status_code == 201
    assert seen["src_id"] == PARANA["src_id"] == "BRA.16_1"
    assert [w["widget_type"] for w in response.json()["widgets"]] == [
        "insight",
        "map",
        "map",
    ]


# ---------------------------------------------------------------------------
# Changing the window
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_default_window_is_two_weeks(client, auth_override):
    """Near-real-time means the last couple of weeks, not a quarter."""
    auth_override("nrt-default-window")
    dashboard = await _create_dashboard(client)

    pull, imagery, summary = _patches()
    with pull, imagery, summary:
        response = await client.post(
            ENDPOINT.format(id=dashboard["id"]), headers=AUTH, json={}
        )

    body = response.json()
    assert body["days"] == 14
    assert body["end_date"] == date.today().isoformat()
    assert (
        body["start_date"] == (date.today() - timedelta(days=14)).isoformat()
    )
    # The section records its own window, so nothing has to read it back
    # out of a tile layer's dates.
    (section,) = body["sections"]
    assert section["config"]["days"] == 14
    assert section["config"]["start_date"] == body["start_date"]


@pytest.mark.asyncio
async def test_refresh_moves_every_widget_to_the_new_window(
    client, auth_override
):
    auth_override("nrt-refresh")
    dashboard = await _create_dashboard(client)

    pull, imagery, summary = _patches()
    with pull, imagery, summary:
        built = await client.post(
            ENDPOINT.format(id=dashboard["id"]), headers=AUTH, json={}
        )
        section_id = built.json()["section_id"]
        old_insight = built.json()["widgets"][0]["insight_id"]

        refreshed = await client.post(
            f"/api/dashboards/{dashboard['id']}/sections/{section_id}/refresh",
            headers=AUTH,
            json={"days": 90},
        )

    assert refreshed.status_code == 200
    body = refreshed.json()
    assert body["days"] == 90
    assert body["created"] is False
    # The section survives: same id, same place, so a link to it holds.
    assert body["section_id"] == section_id
    (section,) = body["sections"]
    assert section["id"] == section_id
    assert section["config"]["days"] == 90

    # Every widget moved together — the alerts layer covers the new window.
    widgets = sorted(body["widgets"], key=lambda w: w["position"])
    assert [w["widget_type"] for w in widgets] == ["insight", "map", "map"]
    alerts = widgets[1]["config"]["dataset"]
    assert alerts["start_date"] == body["start_date"]
    assert f"start_date={body['start_date']}" in alerts["tile_url"]

    # The chart was recomputed, not reused, and the old one is gone.
    assert widgets[0]["insight_id"] != old_insight
    stale = await client.get(f"/api/insights/{old_insight}", headers=AUTH)
    assert stale.status_code == 404


@pytest.mark.asyncio
async def test_refresh_of_a_hand_made_section_is_refused(
    client, auth_override
):
    """A section nobody generated has no recipe to re-run."""
    user = await _create_user("nrt-refresh-plain")
    auth_override(user.id)
    dashboard = await _create_dashboard(client)
    created = await client.post(
        f"/api/dashboards/{dashboard['id']}/sections",
        headers=AUTH,
        json={"title": "My notes"},
    )
    section_id = created.json()["sections"][-1]["id"]

    response = await client.post(
        f"/api/dashboards/{dashboard['id']}/sections/{section_id}/refresh",
        headers=AUTH,
        json={"days": 30},
    )
    assert response.status_code == 422
    assert "no recipe to refresh" in response.json()["detail"]


@pytest.mark.asyncio
async def test_refresh_of_unknown_section_returns_404(client, auth_override):
    auth_override("nrt-refresh-404")
    dashboard = await _create_dashboard(client)

    response = await client.post(
        f"/api/dashboards/{dashboard['id']}/sections/"
        "00000000-0000-0000-0000-000000000000/refresh",
        headers=AUTH,
        json={"days": 30},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_refresh_other_users_dashboard_returns_404(
    client, auth_override
):
    owner = await _create_user("nrt-refresh-owner")
    stranger = await _create_user("nrt-refresh-stranger")
    auth_override(owner.id)
    dashboard = await _create_dashboard(client)

    pull, imagery, summary = _patches()
    with pull, imagery, summary:
        built = await client.post(
            ENDPOINT.format(id=dashboard["id"]), headers=AUTH, json={}
        )
    section_id = built.json()["section_id"]

    auth_override(stranger.id)
    response = await client.post(
        f"/api/dashboards/{dashboard['id']}/sections/{section_id}/refresh",
        headers=AUTH,
        json={"days": 30},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_refresh_window_out_of_range_rejected(client, auth_override):
    auth_override("nrt-refresh-range")
    dashboard = await _create_dashboard(client)

    pull, imagery, summary = _patches()
    with pull, imagery, summary:
        built = await client.post(
            ENDPOINT.format(id=dashboard["id"]), headers=AUTH, json={}
        )
    section_id = built.json()["section_id"]

    response = await client.post(
        f"/api/dashboards/{dashboard['id']}/sections/{section_id}/refresh",
        headers=AUTH,
        json={"days": 400},
    )
    assert response.status_code == 422
