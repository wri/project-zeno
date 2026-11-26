"""Tests for the registry of curated chart views."""

import re
from pathlib import Path
from types import SimpleNamespace

import src.api.services.charts as charts_package
from src.agent.datasets.handlers.analytics_handler import (
    LAND_GHG_INVENTORY_ID,
    TREE_COVER_LOSS_ID,
)
from src.agent.i18n import MESSAGES
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts import ChartGenerator
from src.api.services.charts.curated import build_curated_charts
from src.api.services.charts.registry import DETERMINISTIC_GENERATORS
from src.api.services.charts.views import (
    VIEWS,
    get_view,
    view_for_title,
    views_for_dataset,
)
from tests.unit.api.services.test_chart_generators import LGMS_ROWS

TITLE_KEY = re.compile(r'title="(charts\.[a-z0-9_.]+)"')


def _title_keys_in_generators() -> set[str]:
    """Every chart title key in the source of the generators."""
    keys: set[str] = set()
    for path in Path(charts_package.__file__).parent.glob("*.py"):
        keys.update(TITLE_KEY.findall(path.read_text()))
    return keys


def test_every_chart_a_generator_can_make_is_a_view():
    # A chart with no view is stored with no provenance.
    assert _title_keys_in_generators() == {view.title_key for view in VIEWS}


def test_every_view_title_has_a_message():
    assert [v.id for v in VIEWS if v.title_key not in MESSAGES] == []


def test_every_view_from_a_pull_has_a_registered_generator():
    orphans = [
        view.id
        for view in VIEWS
        if view.from_pull
        and not any(
            g.can_handle(view.dataset_id) for g in DETERMINISTIC_GENERATORS
        )
    ]

    assert orphans == []


def test_view_lookups():
    view = get_view("tcl.annual_loss")

    assert view is not None
    assert view_for_title("charts.tcl.annual_loss") is view
    assert get_view("tcl.unknown") is None
    # A localised or model-written title is not a view.
    assert view_for_title("Annual tree cover loss") is None


def test_views_of_a_dataset_leave_out_template_only_views():
    assert [v.id for v in views_for_dataset(TREE_COVER_LOSS_ID)] == [
        "tcl.annual_loss",
        "tcl.annual_emissions",
    ]
    assert "tcl_natural_forest.annual_split" in [
        v.id for v in views_for_dataset(TREE_COVER_LOSS_ID, from_pull=False)
    ]


async def test_curated_charts_carry_their_view():
    charts = await build_curated_charts(LAND_GHG_INVENTORY_ID, LGMS_ROWS, "en")

    assert [c.view_id for c in charts] == [
        "lgms.annual_average",
        "lgms.full_detail",
        "lgms.by_category",
        "lgms.summary",
    ]
    assert [c.view_revision for c in charts] == [
        get_view(c.view_id).revision for c in charts
    ]


async def test_a_chart_outside_the_registry_has_no_view():
    class UnregisteredGenerator(ChartGenerator):
        dataset_id = 99

        def generate(self, rows):
            return [
                InsightChart(
                    title="Not a view",
                    chart_type="bar",
                    x_axis="year",
                    y_axis="value",
                )
            ]

    (chart,) = await build_curated_charts(
        99, [], "en", [UnregisteredGenerator()]
    )

    assert chart.view_id is None
    assert chart.view_revision is None


def test_view_provenance_goes_to_the_database_and_back():
    chart = InsightChart(
        title="Loss",
        chart_type="bar",
        x_axis="year",
        y_axis="area_ha",
        view_id="tcl.annual_loss",
        view_revision=1,
    )

    kwargs = chart.to_orm_kwargs()
    assert kwargs["view_id"] == "tcl.annual_loss"
    assert kwargs["view_revision"] == 1

    row = SimpleNamespace(**kwargs)
    restored = InsightChart.from_orm_row(row)
    assert restored.view_id == "tcl.annual_loss"
    assert restored.view_revision == 1
    # Provenance is not part of the frontend chart.
    assert "view_id" not in chart.to_frontend_dict()


def test_the_ranking_titles_have_every_language_of_the_annual_titles():
    languages = set(MESSAGES["charts.tcl.annual_loss"])

    for key in ("charts.tcl.loss_ranking", "charts.tcl.emissions_ranking"):
        assert set(MESSAGES[key]) == languages
        assert all(MESSAGES[key].values())
