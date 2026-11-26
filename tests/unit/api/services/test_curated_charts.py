from src.agent.datasets.curated_only import CURATED_ONLY_DATASET_IDS
from src.agent.datasets.handlers.analytics_handler import (
    LAND_GHG_INVENTORY_ID,
    TREE_COVER_LOSS_ID,
)
from src.agent.i18n import t
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts import ChartGenerator
from src.api.services.charts.curated import build_curated_charts
from src.api.services.charts.ranking import RankedArea
from src.api.services.charts.registry import DETERMINISTIC_GENERATORS
from tests.unit.api.services.test_chart_generators import LGMS_ROWS

HANDLED_DATASET_ID = 99


class FakeChartGenerator(ChartGenerator):
    dataset_id = HANDLED_DATASET_ID

    def generate(self, rows):
        return [
            InsightChart(
                position=0,
                title="charts.lgms.summary",
                chart_type="bar",
                x_axis="year",
                y_axis="value",
                chart_data=[{"year": 2020, "value": 1}],
            )
        ]


async def test_no_charts_when_no_generator_handles_the_dataset():
    charts = await build_curated_charts(1, [], "en", [FakeChartGenerator()])

    assert charts == []


async def test_charts_are_localised_and_carry_dataset_id():
    charts = await build_curated_charts(
        HANDLED_DATASET_ID, [], "es", [FakeChartGenerator()]
    )

    assert charts[0].title == await t("charts.lgms.summary", "es")
    # The curated-only guards read `dataset_id` on persisted charts.
    assert charts[0].dataset_id == HANDLED_DATASET_ID


class TwoChartGenerator(ChartGenerator):
    dataset_id = HANDLED_DATASET_ID

    def generate(self, rows):
        return [
            InsightChart(
                position=position,
                title=title,
                chart_type="bar",
                x_axis="year",
                y_axis="value",
                chart_data=[],
            )
            for position, title in enumerate(
                ["charts.tcl.annual_loss", "charts.tcl.annual_emissions"]
            )
        ]


async def test_titles_keep_only_the_named_charts():
    charts = await build_curated_charts(
        HANDLED_DATASET_ID,
        [],
        "en",
        [TwoChartGenerator()],
        titles=["charts.tcl.annual_emissions"],
    )

    (chart,) = charts
    # Picked by key, then localised; first of the charts kept.
    assert chart.title == await t("charts.tcl.annual_emissions", "en")
    assert chart.position == 0


class SeriesKeyedGenerator(ChartGenerator):
    """Series named by message keys, with a colour per series."""

    dataset_id = HANDLED_DATASET_ID
    label_series = True

    def generate(self, rows):
        return [
            InsightChart(
                position=0,
                title="charts.lgms.summary",
                chart_type="stacked-bar",
                x_axis="year",
                series_fields=["charts.label.other", "charts.label.fires"],
                color_map={
                    "charts.label.fires": "#111111",
                    "charts.label.other": "#222222",
                },
                chart_data=[
                    {
                        "year": 2021,
                        "charts.label.other": 1.0,
                        "charts.label.fires": 2.0,
                    }
                ],
            )
        ]


async def test_series_keys_are_localised_with_their_columns_and_colours():
    (chart,) = await build_curated_charts(
        HANDLED_DATASET_ID, [], "es", [SeriesKeyedGenerator()]
    )

    other = await t("charts.label.other", "es")
    fires = await t("charts.label.fires", "es")
    assert chart.series_fields == [other, fires]
    assert chart.chart_data == [{"year": 2021, other: 1.0, fires: 2.0}]
    assert chart.color_map == {fires: "#111111", other: "#222222"}


async def test_series_keys_stay_as_they_are_without_the_flag():
    class RawSeriesGenerator(SeriesKeyedGenerator):
        label_series = False

    (chart,) = await build_curated_charts(
        HANDLED_DATASET_ID, [], "es", [RawSeriesGenerator()]
    )

    assert chart.series_fields == ["charts.label.other", "charts.label.fires"]
    assert "charts.label.fires" in chart.color_map


async def test_default_registry_builds_the_lgms_charts():
    charts = await build_curated_charts(LAND_GHG_INVENTORY_ID, LGMS_ROWS, "en")

    assert len(charts) == 4
    assert all(c.dataset_id == LAND_GHG_INVENTORY_ID for c in charts)
    assert not any(c.title.startswith("charts.") for c in charts)


def test_every_curated_only_dataset_has_a_generator():
    """A `curated_only` dataset with no matching generator would silently
    report "no data" to the user instead of failing loudly (its guard only
    ever sees `build_curated_charts` return [])."""
    unhandled = {
        dataset_id
        for dataset_id in CURATED_ONLY_DATASET_IDS
        if not any(
            generator.can_handle(dataset_id)
            for generator in DETERMINISTIC_GENERATORS
        )
    }

    assert not unhandled


async def test_lgms_charts_group_under_one_insight_id():
    """The four LGMS charts of one analysis must share a `chartBatchKey`
    group so the frontend can fold the three roll-ups behind one DETAIL
    pill; without the shared prefix each chart stands alone and the pill
    has a single option."""
    insight_id = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
    charts = await build_curated_charts(LAND_GHG_INVENTORY_ID, LGMS_ROWS, "en")

    ids = [c.to_frontend_dict(insight_id)["id"] for c in charts]

    assert all(i.startswith(f"{insight_id}-chart-") for i in ids)
    assert len(set(ids)) == len(charts)


# --- the ranking of areas ---------------------------------------------------

_TWO_AREA_ROWS = [
    {
        "aoi_id": "KEN.1",
        "name": "Baringo",
        "tree_cover_loss_year": 2024,
        "area_ha": 3.0,
        "carbon_emissions_MgCO2e": 30.0,
    },
    {
        "aoi_id": "KEN.2",
        "name": "Bomet",
        "tree_cover_loss_year": 2024,
        "area_ha": 9.0,
        "carbon_emissions_MgCO2e": 20.0,
    },
]
_TWO_AREAS = [
    RankedArea("KEN.1", "Baringo", "Kenya", "gadm"),
    RankedArea("KEN.2", "Bomet", "Kenya", "gadm"),
]


async def test_without_areas_the_charts_are_the_annual_pair():
    # /api/analyze and the analysis templates pass no areas.
    charts = await build_curated_charts(
        TREE_COVER_LOSS_ID, _TWO_AREA_ROWS, "en"
    )

    assert [c.view_id for c in charts] == [
        "tcl.annual_loss",
        "tcl.annual_emissions",
    ]
    assert {c.chart_type for c in charts} == {"bar"}
    assert {k for row in charts[0].chart_data for k in row} >= {
        "aoi_id",
        "name",
    }


async def test_with_areas_the_charts_are_the_rankings():
    charts = await build_curated_charts(
        TREE_COVER_LOSS_ID,
        _TWO_AREA_ROWS,
        "en",
        areas=_TWO_AREAS,
        for_agent=True,
    )

    assert [c.view_id for c in charts] == [
        "tcl.loss_ranking",
        "tcl.emissions_ranking",
    ]
    assert [c.title for c in charts] == [
        "Tree Cover Loss by Area",
        "GHG Emissions from Tree Cover Loss by Area",
    ]
    assert [c.view_revision for c in charts] == [1, 1]
    assert set(charts[0].chart_data[0]) == {
        "rank",
        "aoi_id",
        "name",
        "parent",
        "area_ha",
        "share_pct",
    }
    assert charts[0].to_frontend_dict()["type"] == "ranked-bar"
    assert charts[0].to_frontend_dict()["xAxis"] == "name"


async def test_the_titles_of_the_gate_pick_the_rankings():
    charts = await build_curated_charts(
        TREE_COVER_LOSS_ID,
        _TWO_AREA_ROWS,
        "en",
        titles=["charts.tcl.emissions_ranking"],
        areas=_TWO_AREAS,
    )

    assert [c.view_id for c in charts] == ["tcl.emissions_ranking"]
    assert charts[0].position == 0
