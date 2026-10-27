"""Tests for the facts computed from a chart for the description."""

from unittest.mock import patch

import pytest

from src.agent.i18n import MESSAGES
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.analysis_templates.facts import chart_fact
from src.api.services.analysis_templates.models import ChartFact

SENTENCES = {
    "test.total": {
        "en": "{aoi_name} lost {total} ha, {start_year}-{end_year}."
    },
    "test.peak": {"en": "Most in {category}: {value} ha."},
    "test.top_share": {
        "en": "{category}: {share} of the loss ({value} ha of {total} ha)."
    },
    "test.empty": {"en": "No loss in {aoi_name}, {start_year}-{end_year}."},
}


def _chart(rows, x_axis="tree_cover_loss_year", y_axis="area_ha"):
    return InsightChart(
        position=0,
        title="Loss",
        chart_type="bar",
        x_axis=x_axis,
        y_axis=y_axis,
        chart_data=rows,
    )


LOSS = _chart(
    [
        {"tree_cover_loss_year": 2021, "area_ha": 1200.4},
        {"tree_cover_loss_year": 2022, "area_ha": 3400.0},
        {"tree_cover_loss_year": 2023, "area_ha": 3400.0},
    ]
)


async def _fact(kind, chart, empty_key=None):
    with patch.dict(MESSAGES, SENTENCES):
        return await chart_fact(
            ChartFact(kind=kind, text_key=f"test.{kind}", empty_key=empty_key),
            chart,
            aoi_name="Paraná",
            start="2021-01-01",
            end="2023-12-31",
            language="en",
        )


async def test_total_is_the_sum_of_the_areas_over_the_period():
    assert await _fact("total", LOSS) == (
        "Paraná lost 8\u202f000 ha, 2021-2023."
    )


async def test_peak_is_the_first_of_equal_largest_areas():
    assert await _fact("peak", LOSS) == "Most in 2022: 3\u202f400 ha."


async def test_top_share_is_the_largest_category_of_the_sum():
    drivers = _chart(
        [
            {"tree_cover_loss_driver": "Permanent agriculture", "area_ha": 75},
            {"tree_cover_loss_driver": "Logging", "area_ha": 25},
        ],
        x_axis="tree_cover_loss_driver",
    )

    assert await _fact("top_share", drivers) == (
        "Permanent agriculture: 75% of the loss (75 ha of 100 ha)."
    )


async def test_a_year_that_arrives_as_a_float_reads_as_a_year():
    chart = _chart([{"tree_cover_loss_year": 2024.0, "area_ha": 5.0}])

    assert await _fact("peak", chart) == "Most in 2024: 5 ha."


@pytest.mark.parametrize("rows", [[], [{"tree_cover_loss_year": 2021}]])
async def test_no_area_gives_the_empty_sentence(rows):
    assert await _fact("total", _chart(rows), empty_key="test.empty") == (
        "No loss in Paraná, 2021-2023."
    )


async def test_no_area_and_no_empty_sentence_leaves_the_fact_out():
    assert await _fact("peak", _chart([])) is None


async def test_a_chart_that_is_not_an_area_has_no_facts():
    emissions = _chart(
        [{"tree_cover_loss_year": 2021, "carbon_emissions_MgCO2e": 1.0}],
        y_axis="carbon_emissions_MgCO2e",
    )

    with pytest.raises(ValueError, match="hectares"):
        await _fact("total", emissions)
