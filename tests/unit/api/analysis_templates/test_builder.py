"""Tests for the analysis template builder, with the data sources mocked."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.agent.datasets.handlers.analytics_handler import (
    INTEGRATED_ALERTS_ID,
    TREE_COVER_LOSS_ID,
)
from src.agent.datasets.handlers.base import DataPullResult
from src.agent.i18n import MESSAGES
from src.agent.imagery.base import ImageryProviderResult
from src.agent.models import ImageryState
from src.api.services.analysis_templates import builder, text
from src.api.services.analysis_templates.builder import (
    DashboardGoneError,
    NoAreaError,
    WidgetFailedError,
    apply_template,
)
from src.api.services.analysis_templates.models import (
    LayerWidgetSpec,
    NaturalForestLossWidgetSpec,
)
from src.api.services.analysis_templates.registry import (
    Post2020ForestLossArgs,
    get_template,
)
from tests.unit.api.analysis_templates.test_text import _FakeModel
from tests.unit.api.services.test_chart_generators import NATURAL_FOREST_DATA

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
        text=AsyncMock(return_value=("Alerts in Paraná", "What it shows.")),
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
        patch.object(builder, "generate_section_text", mocks.text),
    ]
    return mocks, stack


async def _apply(stack, dashboard=None, args=None, template=NRT):
    for p in stack:
        p.start()
    try:
        return await apply_template(
            dashboard or _dashboard(),
            template,
            template.parse_args(args),
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
    # nrt-monitoring sets no size and no context layer.
    assert not any("size" in w.config for w in widgets)
    assert widgets[1].config["dataset"]["context_layer"] is None


@pytest.mark.asyncio
async def test_layer_with_a_context_layer_and_a_size():
    template = NRT.model_copy(
        update={
            "args_model": Post2020ForestLossArgs,
            "widgets": (
                LayerWidgetSpec(
                    dataset_id=TREE_COVER_LOSS_ID,
                    context_layer="natural_forest",
                    size="single",
                ),
            ),
        }
    )
    mocks, stack = _patches(written=("section-1", ["w1"]))

    await _apply(stack, template=template)

    (widget,) = mocks.write.await_args.kwargs["widgets"]
    assert widget.config["size"] == "single"
    dataset = widget.config["dataset"]
    assert dataset["context_layer"] == "natural_forest"
    # The frontend draws natural forest from this context tile.
    (context,) = dataset["context_layers"]
    assert context["name"] == "natural_forest"
    assert context["tile_url"]
    # The period, clamped to the end of the loss data.
    assert (dataset["start_date"], dataset["end_date"]) == (
        "2021-01-01",
        "2025-12-31",
    )
    assert "tree_cover_density_threshold=0" in dataset["tile_url"]
    assert dataset["tile_url"].endswith("&start_year=2021&end_year=2025")


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


SHARE_FACT = (
    "From 2021 to 2025, 84% of the tree cover loss in Paraná was in "
    "natural forest: 4\u202f423 ha of 5\u202f286 ha."
)
SPLIT = NRT.model_copy(
    update={
        "args_model": Post2020ForestLossArgs,
        "widgets": (NaturalForestLossWidgetSpec(),),
    }
)


def _split_pull(classes_and_areas):
    """A breakdown answer with one row per (class, area), all in 2022."""
    return _pull(
        data={
            "tree_cover_loss_year": [2022] * len(classes_and_areas),
            "natural_forests_class": [c for c, _ in classes_and_areas],
            "area_ha": [a for _, a in classes_and_areas],
        }
    )


@pytest.mark.asyncio
async def test_natural_forest_loss_pulls_the_breakdown_from_2021():
    mocks, stack = _patches(
        pull=_pull(data=NATURAL_FOREST_DATA), written=("section-1", ["w1"])
    )

    await _apply(stack, template=SPLIT)

    pull = mocks.pull.await_args.kwargs
    assert pull["dataset"] == {
        "dataset_id": TREE_COVER_LOSS_ID,
        "forest_breakdown": "natural_forest",
    }
    # From the natural forest baseline to the last year of loss data.
    assert (pull["start_date"], pull["end_date"]) == (
        "2021-01-01",
        "2025-12-31",
    )
    (widget,) = mocks.write.await_args.kwargs["widgets"]
    assert (widget.widget_type, widget.config) == ("insight", {})
    (chart,) = widget.insight.charts
    assert chart.series_fields == ["Other tree cover", "Natural forest"]
    assert chart.color_map == {
        "Natural forest": "#246E24",
        "Other tree cover": "#DC6C9A",
    }


@pytest.mark.asyncio
async def test_natural_forest_share_is_a_computed_fact():
    mocks, stack = _patches(
        pull=_pull(data=NATURAL_FOREST_DATA), written=("section-1", ["w1"])
    )

    await _apply(stack, template=SPLIT)

    # 4,422.85 ha of 5,285.86 ha is 83.7%.
    assert mocks.text.await_args.kwargs["facts"] == [SHARE_FACT]


@pytest.mark.asyncio
async def test_no_loss_is_a_fact_and_a_chart_of_zeros():
    mocks, stack = _patches(pull=_pull(data={}), written=("section-1", ["w1"]))

    await _apply(stack, template=SPLIT)

    assert mocks.text.await_args.kwargs["facts"] == [
        "No tree cover loss was recorded in Paraná from 2021 to 2025."
    ]
    (widget,) = mocks.write.await_args.kwargs["widgets"]
    assert len(widget.insight.charts[0].chart_data) == 5


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("natural_ha", "other_ha", "fact_end"),
    [
        (
            0.4,
            999.6,
            "<1% of the tree cover loss in Paraná was in natural "
            "forest: <1 ha of 1\u202f000 ha.",
        ),
        (
            999.6,
            0.4,
            ">99% of the tree cover loss in Paraná was in natural "
            "forest: 1\u202f000 ha of 1\u202f000 ha.",
        ),
    ],
)
async def test_a_small_part_never_rounds_to_0_or_100_percent(
    natural_ha, other_ha, fact_end
):
    pull = _split_pull([("Natural Forest", natural_ha), ("Unknown", other_ha)])
    mocks, stack = _patches(pull=pull, written=("section-1", ["w1"]))

    await _apply(stack, template=SPLIT)

    (fact,) = mocks.text.await_args.kwargs["facts"]
    assert fact.endswith(fact_end)


@pytest.mark.asyncio
async def test_unknown_natural_forest_class_writes_nothing():
    pull = _split_pull([("Natural Grassland", 10.0)])
    mocks, stack = _patches(pull=pull, written=("section-1", ["w1"]))

    with pytest.raises(WidgetFailedError, match="natural forest class"):
        await _apply(stack, template=SPLIT)

    mocks.write.assert_not_awaited()


@pytest.mark.parametrize(
    "key",
    [
        "analysis_template.natural_forest_loss.share",
        "analysis_template.natural_forest_loss.no_loss",
    ],
)
def test_natural_forest_facts_take_their_placeholders_in_every_language(key):
    values = {
        "aoi_name": "A",
        "start_year": "2021",
        "end_year": "2025",
        "share": "84%",
        "natural_ha": "1",
        "total_ha": "2",
    }
    for message in MESSAGES[key].values():
        assert "A" in message.format(**values)


POST_2020 = get_template("post-2020-forest-loss")


async def _apply_post_2020():
    # A model that records its prompt, then fails, so the section gets the
    # fallback text.
    model = _FakeModel(RuntimeError("no model in unit tests"))
    mocks, stack = _patches(
        pull=_pull(data=NATURAL_FOREST_DATA),
        written=("section-1", ["w1", "w2", "w3"]),
    )

    async def _text(*args, **kwargs):
        return await text.generate_section_text(*args, model=model, **kwargs)

    mocks.text.side_effect = _text
    result = await _apply(stack, template=POST_2020)
    return result, mocks, model


@pytest.mark.asyncio
async def test_post_2020_forest_loss_builds_its_three_widgets():
    _, mocks, _ = await _apply_post_2020()

    kwargs = mocks.write.await_args.kwargs
    chart, layer, imagery = kwargs["widgets"]
    assert (chart.widget_type, chart.config) == ("insight", {})
    # The two maps share a row; the chart takes the full width.
    assert layer.config["size"] == imagery.config["size"] == "single"
    dataset = layer.config["dataset"]
    assert dataset["context_layer"] == "natural_forest"
    assert [c["name"] for c in dataset["context_layers"]] == ["natural_forest"]
    assert dataset["context_layers"][0]["tile_url"]
    # The map covers the chart's years.
    assert (dataset["start_date"], dataset["end_date"]) == (
        "2021-01-01",
        "2025-12-31",
    )
    assert dataset["tile_url"].endswith("&start_year=2021&end_year=2025")
    (request,) = mocks.imagery.await_args.args
    assert (request.target_date, request.window_days) == (TODAY, 30)
    assert kwargs["template"]["name"] == "post-2020-forest-loss"
    assert kwargs["template"]["args"] == {}
    assert kwargs["template"]["start_date"] == "2021-01-01"


@pytest.mark.asyncio
async def test_post_2020_prompt_has_the_share_and_the_clamped_years():
    _, _, model = await _apply_post_2020()

    # The section period runs to today (for the imagery); the fact and the
    # widget lines carry the years of the data.
    assert "## Period\n2021-01-01 to 2026-09-23" in model.inputs
    assert "## Facts\n" in model.inputs
    assert f"- {SHARE_FACT}" in model.inputs
    assert "2021-01-01 to 2025-12-31" in model.inputs
    assert (
        "map layer: Tree cover loss with the natural_forest context layer, "
        "2021-01-01 to 2025-12-31"
    ) in model.inputs
    assert "Take every figure and every year from the facts" in model.inputs


@pytest.mark.asyncio
async def test_post_2020_fallback_states_the_share_then_the_caveats():
    result, _, _ = await _apply_post_2020()

    assert result.title == "Post-2020 forest loss in Paraná"
    assert result.description.startswith(
        f"{SHARE_FACT} The SBTN Natural Lands Map is a 2020 baseline"
    )
    assert "30%" in result.description
