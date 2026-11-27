"""A recalled or an updated curated insight gives its facts: its summary
is a caption with no figures."""

import pytest

from src.agent.datasets.handlers.analytics_handler import (
    INTEGRATED_ALERTS_ID,
    LAND_GHG_INVENTORY_ID,
)
from src.agent.subagents.analyst.charts import InsightChart
from src.agent.subagents.analyst.charts.model import Insight
from src.agent.subagents.analyst.curated_first import curated_facts_text
from src.agent.subagents.analyst.display_reviser import (
    RevisedChart,
    RevisedInsight,
)
from src.agent.tools.search_insights import _recalled_message
from src.agent.tools.update_insight_display import _apply_revision


def _chart(view_id):
    return InsightChart(
        title="Annual Tree Cover Loss",
        chart_type="bar",
        x_axis="tree_cover_loss_year",
        y_axis="area_ha",
        chart_data=[
            {"tree_cover_loss_year": 2021, "area_ha": 100.0},
            {"tree_cover_loss_year": 2022, "area_ha": 300.0},
        ],
        view_id=view_id,
    )


def test_curated_chart_gives_its_facts():
    text = curated_facts_text([_chart("tcl.annual_loss")])
    assert "Facts of Annual Tree Cover Loss (computed in code):" in text
    assert "Total area_ha from 2021 to 2022: 400 ha." in text


def test_custom_chart_gives_no_facts():
    assert curated_facts_text([_chart(None)]) == ""


def test_recall_of_a_curated_insight_has_the_facts():
    insight = Insight(
        charts=[_chart("tcl.annual_loss")],
        primary_insight="Standard Tree cover loss charts for Pará, 2021–2022.",
    )
    message = _recalled_message("insight-1", insight, "loss in Pará")
    assert "Total area_ha from 2021 to 2022: 400 ha." in message
    assert message.index("Total area_ha") < message.index("STOP HERE")


def test_recall_of_a_custom_insight_is_as_before():
    insight = Insight(charts=[_chart(None)], primary_insight="A summary.")
    message = _recalled_message("insight-1", insight, "loss")
    assert "Summary: A summary.\n\nSTOP HERE." in message


# --- only released views, never a curated-only dataset ---------------------


def test_an_lgms_chart_gives_no_facts():
    # build_curated_charts stamps a view_id on the LGMS charts too, and
    # search_insights runs on the default and the lgms profiles.
    chart = InsightChart(
        title="Land emissions and removals",
        chart_type="stacked-bar",
        x_axis="year",
        y_axis="value",
        series_fields=["Emissions", "Removals"],
        chart_data=[{"year": 2020, "Emissions": 5.0, "Removals": -3.0}],
        dataset_id=LAND_GHG_INVENTORY_ID,
        view_id="lgms.summary",
    )
    assert curated_facts_text([chart]) == ""
    insight = Insight(charts=[chart], primary_insight="Standard charts.")
    message = _recalled_message("insight-1", insight, "lgms")
    assert "Facts of" not in message


def test_a_view_that_is_not_released_gives_no_facts():
    chart = _chart("tcl_natural_forest.annual_split")
    assert curated_facts_text([chart]) == ""


# --- a restyle keeps the view -----------------------------------------------


def _alerts_chart():
    return InsightChart(
        position=0,
        title="Integrated alerts",
        chart_type="stacked-bar",
        x_axis="alert_date",
        y_axis="area_ha",
        series_fields=["Highest", "High"],
        color_map={"Highest": "#111111", "High": "#222222"},
        chart_data=[
            {"alert_date": "2026-08-01", "Highest": 2.0, "High": 5.0},
            {"alert_date": "2026-08-02", "Highest": 4.0, "High": 1.0},
        ],
        dataset_id=INTEGRATED_ALERTS_ID,
        view_id="integrated_alerts.by_confidence",
        view_revision=1,
    )


def _revision(**changes):
    chart = {
        "position": 0,
        "title": "Alerts by day",
        "chart_type": "grouped-bar",
        "x_axis": "alert_date",
        "y_axis": "area_ha",
        "series_fields": ["Highest", "High"],
        **changes,
    }
    return RevisedInsight(
        primary_insight="Standard charts.",
        follow_up_suggestions=[],
        charts=[RevisedChart(**chart)],
    )


def test_a_restyle_keeps_the_view_its_colours_and_its_facts():
    (chart,) = _apply_revision([_alerts_chart()], _revision()).charts
    assert chart.chart_type == "grouped-bar"
    assert chart.view_id == "integrated_alerts.by_confidence"
    assert chart.view_revision == 1
    assert chart.color_map == {"Highest": "#111111", "High": "#222222"}
    assert "Total all series: 12 ha." in curated_facts_text([chart])


def test_a_restyle_of_other_series_resolves_the_colours_again():
    (chart,) = _apply_revision(
        [_alerts_chart()], _revision(series_fields=["Highest"])
    ).charts
    assert chart.view_id == "integrated_alerts.by_confidence"
    assert chart.color_map != {"Highest": "#111111", "High": "#222222"}


# --- a restyle keeps a ranking a ranked bar when its measure is kept --------


def _ranking():
    return InsightChart(
        position=0,
        title="Tree cover loss by area",
        chart_type="ranked-bar",
        x_axis="name",
        y_axis="area_ha",
        chart_data=[
            {"rank": 1, "name": "A", "area_ha": 9.0, "other_ha": 1.0},
            {"rank": 2, "name": "B", "area_ha": 5.0, "other_ha": 2.0},
        ],
        view_id="tcl.loss_ranking",
    )


def _revised(chart_type, y_axis="area_ha"):
    return RevisedInsight(
        charts=[
            RevisedChart(
                position=0,
                title="Renamed",
                chart_type=chart_type,
                x_axis="name",
                y_axis=y_axis,
            )
        ],
        primary_insight="Summary.",
        follow_up_suggestions=[],
    )


@pytest.mark.parametrize(
    "chart_type, y_axis, expected",
    [
        # The same measure in a bar keeps the ranked bar.
        ("bar", "area_ha", "ranked-bar"),
        ("pie", "area_ha", "pie"),
        # Another measure has no rank to show: a plain bar.
        ("bar", "other_ha", "bar"),
    ],
)
def test_a_restyle_of_a_ranking_takes_the_type_that_fits(
    chart_type, y_axis, expected
):
    insight = _apply_revision([_ranking()], _revised(chart_type, y_axis))

    assert insight.charts[0].chart_type == expected
    assert insight.charts[0].title == "Renamed"
