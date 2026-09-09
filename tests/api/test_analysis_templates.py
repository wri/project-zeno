"""Tests for what an analysis template writes, against a real database.

The template composes three slow things — an analytics pull, a mosaic build
and a model call — so every test here stands them in. What is under test is
the composition: what the section contains, what happens when a part fails,
that a second build does not produce a second section, and that a refresh
moves every widget together while the section row survives.

These go through the template object, which is what the agent tools call.
The rows are read back through the repository, so a claim about a widget's
config is a claim about what is stored.
"""

from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from src.agent.datasets.handlers.analytics_handler import INTEGRATED_ALERTS_ID
from src.agent.datasets.handlers.base import DataPullResult
from src.agent.imagery.base import ImageryProviderResult
from src.agent.models import ImageryState
from src.api.data_models import UserOrm
from src.api.repositories import dashboard_writer
from src.api.services.analysis_templates import registry
from src.api.services.analysis_templates.base import (
    AlreadyBuiltError,
    DataUnavailableError,
    stored_params,
)
from src.api.services.analysis_templates.nrt_monitoring import (
    NAME,
    NrtParams,
)
from src.api.services.analysis_templates.nrt_monitoring.summary import (
    SectionSummary,
)
from tests.conftest import async_session_maker

PARANA = {
    "source": "gadm",
    "src_id": "BRA.16_1",
    "subtype": "state-province",
    "name": "Paraná",
}

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

TEMPLATE = registry.get_template(NAME)


async def _create_user(user_id: str) -> UserOrm:
    async with async_session_maker() as session:
        user = UserOrm(
            id=user_id, name=user_id, email=f"{user_id}@example.com"
        )
        session.add(user)
        await session.commit()
        return user


async def _dashboard(user_id: str, aois=(PARANA,)):
    """A dashboard row, loaded the way the tools load it.

    ``aois`` defaults to one area; pass ``[]`` for a dashboard with none.
    """
    await _create_user(user_id)
    dashboard_id = await dashboard_writer.create_dashboard(
        user_id=user_id, name="Paraná", aois=list(aois)
    )
    return await dashboard_writer.get_dashboard(dashboard_id)


async def _reload(dashboard):
    return await dashboard_writer.get_dashboard(str(dashboard.id))


def _patches(
    *,
    pull_success: bool = True,
    imagery: ImageryProviderResult | None = None,
    imagery_spy: dict | None = None,
):
    """Stand in for the three slow collaborators of the template.

    The pull stand-in **mutates its ``aois`` argument** exactly as the real
    ``AnalyticsHandler`` does (it strips the GADM level suffix in place), so
    a template that shares one AOI dict between the data pull and the
    imagery lookup fails here rather than only in production.
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
            "src.api.services.analysis_templates.nrt_monitoring.recipe."
            "_IMAGERY_PROVIDER.get_imagery",
            _get_imagery,
        ),
        patch(
            "src.api.services.analysis_templates.nrt_monitoring.recipe."
            "generate_section_summary",
            AsyncMock(return_value=SUMMARY),
        ),
    )


async def _build(dashboard, *, user_id, days=None):
    params = NrtParams(**({} if days is None else {"days": days}))
    return await TEMPLATE.build(
        dashboard, user_id=user_id, params=params, language="en"
    )


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_builds_a_sealed_section_with_three_widgets():
    dashboard = await _dashboard("tpl-owner")

    pull, imagery, summary = _patches()
    with pull, imagery, summary:
        result = await _build(dashboard, user_id="tpl-owner")

    assert result.template == NAME
    assert result.warnings == []

    stored = await _reload(dashboard)
    (section,) = stored.sections
    assert str(section.id) == result.section_id
    # Sealed by being registered, not by anything the template did.
    assert section.type == NAME
    assert section.type in dashboard_writer.SEALED_SECTION_TYPES
    assert section.title == SUMMARY.title
    assert section.description == SUMMARY.description
    # The section records which template owns it, so a rebuild knows what
    # to re-run, and the parameters it ran with, so a refresh needs none.
    assert section.config["template"] == NAME
    assert section.config["params"] == {"days": 14}

    widgets = sorted(stored.widgets, key=lambda w: w.position)
    assert [w.widget_type for w in widgets] == ["insight", "map", "map"]
    assert all(w.section_id == section.id for w in widgets)

    # The alerts layer covers the same period the chart does.
    alerts = widgets[1].config["dataset"]
    assert alerts["dataset_id"] == INTEGRATED_ALERTS_ID
    assert f"start_date={alerts['start_date']}" in alerts["tile_url"]
    assert alerts["end_date"] == date.today().isoformat()

    assert widgets[2].config["imagery"]["mosaic_id"] == "token-1"


@pytest.mark.asyncio
async def test_default_window_is_two_weeks():
    """Near-real-time means the last couple of weeks, not a quarter."""
    dashboard = await _dashboard("tpl-default-window")

    pull, imagery, summary = _patches()
    with pull, imagery, summary:
        await _build(dashboard, user_id="tpl-default-window")

    (section,) = (await _reload(dashboard)).sections
    # The section records its own window, so nothing has to read it back out
    # of a tile layer's dates.
    assert section.config["days"] == 14
    assert section.config["end_date"] == date.today().isoformat()
    assert (
        section.config["start_date"]
        == (date.today() - timedelta(days=14)).isoformat()
    )


@pytest.mark.asyncio
async def test_imagery_failure_still_builds_the_section():
    dashboard = await _dashboard("tpl-no-imagery")

    pull, imagery, summary = _patches(
        imagery=ImageryProviderResult(
            status="error", message="AOI is too large for mosaics."
        )
    )
    with pull, imagery, summary:
        result = await _build(dashboard, user_id="tpl-no-imagery")

    assert result.warnings == ["AOI is too large for mosaics."]
    stored = await _reload(dashboard)
    assert len(stored.sections) == 1
    assert [w.widget_type for w in stored.widgets] == ["insight", "map"]


@pytest.mark.asyncio
async def test_analytics_failure_builds_nothing():
    """A section without its data says nothing, so none is written."""
    dashboard = await _dashboard("tpl-no-data")

    pull, imagery, summary = _patches(pull_success=False)
    with pull, imagery, summary:
        with pytest.raises(DataUnavailableError):
            await _build(dashboard, user_id="tpl-no-data")

    stored = await _reload(dashboard)
    assert stored.sections == []
    assert stored.widgets == []


@pytest.mark.asyncio
async def test_second_build_for_the_same_period_is_refused():
    dashboard = await _dashboard("tpl-twice")

    pull, imagery, summary = _patches()
    with pull, imagery, summary:
        first = await _build(dashboard, user_id="tpl-twice")
        with pytest.raises(AlreadyBuiltError) as error:
            await _build(await _reload(dashboard), user_id="tpl-twice")

    assert error.value.section_id == first.section_id
    assert len((await _reload(dashboard)).sections) == 1


@pytest.mark.asyncio
async def test_a_different_period_builds_a_second_section():
    """The guard is against a double click, not against two windows."""
    dashboard = await _dashboard("tpl-two-windows")

    pull, imagery, summary = _patches()
    with pull, imagery, summary:
        await _build(dashboard, user_id="tpl-two-windows", days=14)
        await _build(
            await _reload(dashboard), user_id="tpl-two-windows", days=90
        )

    assert len((await _reload(dashboard)).sections) == 2


@pytest.mark.asyncio
async def test_dashboard_without_an_area_is_refused():
    """Refused before anything is pulled: the section covers an area."""
    dashboard = await _dashboard("tpl-no-aoi", aois=[])

    pull, imagery, summary = _patches()
    with pull, imagery, summary:
        with pytest.raises(DataUnavailableError):
            await _build(dashboard, user_id="tpl-no-aoi")

    assert (await _reload(dashboard)).sections == []


@pytest.mark.asyncio
async def test_imagery_gets_the_canonical_aoi_id():
    """The data pull rewrites its input in place — the analytics API wants a
    GADM id without the level suffix. The imagery lookup that follows must
    still see the id the dashboard stored, or it resolves no geometry and
    the section silently loses its satellite widget."""
    dashboard = await _dashboard("tpl-aoi-id")
    seen: dict = {}

    pull, imagery, summary = _patches(imagery_spy=seen)
    with pull, imagery, summary:
        await _build(dashboard, user_id="tpl-aoi-id")

    assert seen["src_id"] == PARANA["src_id"] == "BRA.16_1"
    stored = await _reload(dashboard)
    assert [w.widget_type for w in stored.widgets] == [
        "insight",
        "map",
        "map",
    ]


# ---------------------------------------------------------------------------
# Refreshing
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_refresh_moves_every_widget_to_the_new_window():
    dashboard = await _dashboard("tpl-refresh")

    pull, imagery, summary = _patches()
    with pull, imagery, summary:
        built = await _build(dashboard, user_id="tpl-refresh")
        stored = await _reload(dashboard)
        (section,) = stored.sections
        old_insight = sorted(stored.widgets, key=lambda w: w.position)[
            0
        ].insight_id

        refreshed = await TEMPLATE.refresh(
            section,
            stored,
            user_id="tpl-refresh",
            params=NrtParams(days=90),
            language="en",
        )

    # The section survives: same id, same place, so a link to it holds.
    assert refreshed.section_id == built.section_id

    stored = await _reload(dashboard)
    (section,) = stored.sections
    assert section.config["days"] == 90
    assert (
        section.config["start_date"]
        == (date.today() - timedelta(days=90)).isoformat()
    )

    # Every widget moved together — the alerts layer covers the new window.
    widgets = sorted(stored.widgets, key=lambda w: w.position)
    assert [w.widget_type for w in widgets] == ["insight", "map", "map"]
    alerts = widgets[1].config["dataset"]
    assert alerts["start_date"] == section.config["start_date"]
    assert f"start_date={section.config['start_date']}" in alerts["tile_url"]

    # The chart was recomputed, not reused, and the old one is gone: it was
    # this section's own content, for a period it no longer covers.
    assert widgets[0].insight_id != old_insight
    async with async_session_maker() as session:
        from src.api.data_models import InsightOrm

        assert await session.get(InsightOrm, old_insight) is None


@pytest.mark.asyncio
async def test_a_section_can_be_re_run_from_what_it_recorded():
    """The round trip a refresh depends on: the parameters a section stored
    rebuild it without the caller naming any."""
    dashboard = await _dashboard("tpl-round-trip")

    pull, imagery, summary = _patches()
    with pull, imagery, summary:
        await _build(dashboard, user_id="tpl-round-trip", days=30)
        stored = await _reload(dashboard)
        (section,) = stored.sections

        await TEMPLATE.refresh(
            section,
            stored,
            user_id="tpl-round-trip",
            params=stored_params(TEMPLATE, section),
            language="en",
        )

    (section,) = (await _reload(dashboard)).sections
    assert section.config["params"] == {"days": 30}
    assert (
        section.config["start_date"]
        == (date.today() - timedelta(days=30)).isoformat()
    )


@pytest.mark.asyncio
async def test_the_template_describes_its_own_section():
    """A caller is told what the section covers without reading its config
    or a widget's tile layer."""
    dashboard = await _dashboard("tpl-describe")

    pull, imagery, summary = _patches()
    with pull, imagery, summary:
        await _build(dashboard, user_id="tpl-describe", days=30)

    (section,) = (await _reload(dashboard)).sections
    assert TEMPLATE.describe(section) == (
        f"{(date.today() - timedelta(days=30)).isoformat()} to "
        f"{date.today().isoformat()}"
    )


@pytest.mark.asyncio
async def test_refresh_rewrites_the_words_because_they_state_the_period():
    dashboard = await _dashboard("tpl-refresh-words")

    pull, imagery, summary = _patches()
    with pull, imagery, summary:
        await _build(dashboard, user_id="tpl-refresh-words")
        stored = await _reload(dashboard)
        (section,) = stored.sections

        moved = SectionSummary(
            title="Alerts in Paraná, last 30 days",
            description="14.0 ha of alerts.",
        )
        with patch(
            "src.api.services.analysis_templates.nrt_monitoring.recipe."
            "generate_section_summary",
            AsyncMock(return_value=moved),
        ):
            await TEMPLATE.refresh(
                section,
                stored,
                user_id="tpl-refresh-words",
                params=NrtParams(days=30),
                language="en",
            )

    (section,) = (await _reload(dashboard)).sections
    assert section.title == moved.title
    assert section.description == moved.description
