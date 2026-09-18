from src.agent.datasets.curated_only import CURATED_ONLY_DATASET_IDS
from src.agent.datasets.handlers.analytics_handler import LAND_GHG_INVENTORY_ID
from src.agent.i18n import t
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts import ChartGenerator
from src.api.services.charts.curated import build_curated_charts
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
