"""A recalled or an updated curated insight gives its facts: its summary
is a caption with no figures."""

from src.agent.subagents.analyst.charts import InsightChart
from src.agent.subagents.analyst.charts.model import Insight
from src.agent.subagents.analyst.curated_first import curated_facts_text
from src.agent.tools.search_insights import _recalled_message


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
