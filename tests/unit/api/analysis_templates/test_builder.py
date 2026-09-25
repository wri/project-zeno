"""Tests for the analysis template builder, with the data sources mocked."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.agent.datasets.handlers.analytics_handler import INTEGRATED_ALERTS_ID
from src.agent.datasets.handlers.base import DataPullResult
from src.agent.imagery.base import ImageryProviderResult
from src.agent.models import ImageryState
from src.api.services.analysis_templates import builder
from src.api.services.analysis_templates.builder import (
    DashboardGoneError,
    NoAreaError,
    WidgetFailedError,
    apply_template,
)
from src.api.services.analysis_templates.registry import get_template

NRT = get_template("nrt-monitoring")
TODAY = date(2026, 9, 23)
ROWS = {
    "alert_date": ["2026-09-10", "2026-09-10", "2026-09-12"],
    "alert_confidence": ["high", "high", "low"],
    "area_ha": [1.25, 2.0, 0.5],
}


def _dashboard(aois=None):
    return SimpleNamespace(
        id=uuid4(),
        name="Paraná",
        aois=[
            SimpleNamespace(
                source="gadm",
                src_id="BRA.16_1",
                subtype="state-province",
                name="Paraná",
                position=0,
            )
        ]
        if aois is None
        else aois,
    )


def _pull(success=True, data=None, message=""):
    return DataPullResult(
        success=success,
        data=ROWS if data is None else data,
        message=message,
    )


def _imagery():
    return ImageryProviderResult(
        status="success",
        message="ok",
        imagery=ImageryState(
            provider="sentinel-2",
            tile_url="https://titiler/mosaic/{z}/{x}/{y}",
            mosaic_id="mosaic-1",
            target_date="2026-09-23",
            aoi_names=["Paraná"],
        ),
    )


def _patches(pull=None, imagery=None, written=("section-1", ["w1", "w2"])):
    """Mock the analytics pull, the mosaic search and the database write."""
    mocks = SimpleNamespace(
        pull=AsyncMock(return_value=pull or _pull()),
        imagery=AsyncMock(return_value=imagery or _imagery()),
        write=AsyncMock(return_value=written),
    )

    class _Today(date):
        calls = 0

        @classmethod
        def today(cls):
            cls.calls += 1
            return TODAY

    mocks.today = _Today
    stack = [
        patch.object(
            builder.AnalyticsHandler, "pull_data", mocks.pull, create=True
        ),
        patch.object(builder._IMAGERY_PROVIDER, "get_imagery", mocks.imagery),
        patch.object(
            builder.dashboard_writer, "add_section_with_widgets", mocks.write
        ),
        patch.object(builder, "date", _Today),
        patch.object(
            builder,
            "generate_section_text",
            AsyncMock(return_value=("Alerts in Paraná", "What it shows.")),
        ),
    ]
    return mocks, stack


async def _apply(stack, dashboard=None, args=None):
    for p in stack:
        p.start()
    try:
        return await apply_template(
            dashboard or _dashboard(),
            NRT,
            NRT.parse_args(args),
            "user-1",
            "en",
        )
    finally:
        for p in stack:
            p.stop()


@pytest.mark.asyncio
async def test_builds_three_widgets_in_template_order():
    mocks, stack = _patches(written=("section-1", ["w1", "w2", "w3"]))

    result = await _apply(stack)

    assert result.section_id == "section-1"
    assert result.warnings == []
    assert (result.title, result.description) == (
        "Alerts in Paraná",
        "What it shows.",
    )
    kwargs = mocks.write.await_args.kwargs
    widgets = kwargs["widgets"]
    assert [w.widget_type for w in widgets] == ["insight", "map", "map"]
    chart = widgets[0].insight.charts[0]
    assert chart.dataset_id == INTEGRATED_ALERTS_ID
    assert chart.x_axis == "alert_date"
    assert widgets[1].config["dataset"]["dataset_id"] == INTEGRATED_ALERTS_ID
    assert widgets[1].config["dataset"]["end_date"] == "2026-09-23"
    assert widgets[2].config["imagery"]["mosaic_id"] == "mosaic-1"
    assert kwargs["user_id"] == "user-1"


@pytest.mark.asyncio
async def test_template_record_and_one_today():
    mocks, stack = _patches(written=("section-1", ["w1", "w2", "w3"]))

    await _apply(stack, args={"days": 30})

    record = mocks.write.await_args.kwargs["template"]
    assert record["name"] == "nrt-monitoring"
    assert record["args"] == {"days": 30}
    assert record["start_date"] == "2026-08-24"
    assert record["end_date"] == "2026-09-23"
    assert mocks.today.calls == 1


@pytest.mark.asyncio
async def test_args_default_to_the_template_default():
    mocks, stack = _patches()

    await _apply(stack)

    assert mocks.write.await_args.kwargs["template"]["args"] == {"days": 14}
    assert mocks.pull.await_args.kwargs["start_date"] == "2026-09-09"


@pytest.mark.asyncio
async def test_required_failure_writes_nothing():
    mocks, stack = _patches(pull=_pull(success=False, message="API down"))

    with pytest.raises(WidgetFailedError, match="API down"):
        await _apply(stack)

    mocks.write.assert_not_awaited()


@pytest.mark.asyncio
async def test_unexpected_error_in_required_widget_writes_nothing():
    mocks, stack = _patches()
    mocks.pull.side_effect = RuntimeError("boom")

    with pytest.raises(WidgetFailedError):
        await _apply(stack)

    mocks.write.assert_not_awaited()


@pytest.mark.asyncio
async def test_optional_failure_gives_a_warning_and_drops_the_widget():
    no_imagery = ImageryProviderResult(
        status="error", message="No cloud-free imagery in the period."
    )
    mocks, stack = _patches(imagery=no_imagery)

    result = await _apply(stack)

    assert result.warnings == ["No cloud-free imagery in the period."]
    widgets = mocks.write.await_args.kwargs["widgets"]
    assert [w.widget_type for w in widgets] == ["insight", "map"]


@pytest.mark.asyncio
async def test_each_builder_gets_its_own_aoi_copy():
    mocks, stack = _patches()

    async def mutating_pull(**kwargs):
        # The analytics handler strips the GADM level suffix in place.
        kwargs["aois"][0]["src_id"] = "BRA.16"
        return _pull()

    mocks.pull.side_effect = mutating_pull

    await _apply(stack)

    (request,) = mocks.imagery.await_args.args
    assert request.aois[0]["src_id"] == "BRA.16_1"
    assert request.target_date == TODAY


@pytest.mark.asyncio
async def test_empty_period_builds_an_empty_chart():
    mocks, stack = _patches(pull=_pull(data={}))

    await _apply(stack)

    widgets = mocks.write.await_args.kwargs["widgets"]
    assert widgets[0].insight.charts[0].chart_data == []


@pytest.mark.asyncio
async def test_no_area_is_an_error():
    mocks, stack = _patches()

    with pytest.raises(NoAreaError):
        await _apply(stack, dashboard=_dashboard(aois=[]))

    mocks.pull.assert_not_awaited()


@pytest.mark.asyncio
async def test_dashboard_deleted_during_the_build():
    _, stack = _patches(written=None)

    with pytest.raises(DashboardGoneError):
        await _apply(stack)
