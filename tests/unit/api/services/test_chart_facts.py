"""Tests for the facts computed from a chart for the description."""

from unittest.mock import patch

import pytest

from src.agent.i18n import MESSAGES
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.facts import (
    ChartFact,
    Fact,
    chart_facts,
    is_time_axis,
    measure_facts,
    number,
    unit_of,
)

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
    """The one fact's sentence, or None when it gives none."""
    with patch.dict(MESSAGES, SENTENCES):
        sentences = await chart_facts(
            [
                ChartFact(
                    kind=kind, text_key=f"test.{kind}", empty_key=empty_key
                )
            ],
            chart,
            aoi_name="Paraná",
            start="2021-01-01",
            end="2023-12-31",
            language="en",
        )
    return sentences[0] if sentences else None


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


# --- measure facts for the agent ---------------------------------------------


def _bar(rows, x_axis="year", y_axis="area_ha", series=None):
    return InsightChart(
        position=0,
        title="t",
        chart_type="stacked-bar" if series else "bar",
        x_axis=x_axis,
        y_axis=y_axis,
        chart_data=rows,
        series_fields=series or [],
    )


def test_unit_of():
    assert unit_of("area_ha") == "ha"
    assert unit_of("carbon_emissions_MgCO2e") == "MgCO2e"
    assert unit_of("gross_emissions_MgCO2e") == "MgCO2e"
    assert unit_of("emissions_tCO2e") == "tCO2e"
    assert unit_of("natural_ha") == "ha"
    assert unit_of("share_pct") == "%"
    assert unit_of("count") == ""


def test_number():
    assert number(2021.0) == "2021"
    assert number(12) == "12"
    assert number(1234.5678) == "1234.57"
    assert number(0.012345) == "0.01235"
    assert number(-3.5) == "-3.50"


def test_time_axis():
    assert is_time_axis(_bar([{"year": 2020}]))
    assert is_time_axis(_bar([{"x": 2020}, {"x": 2021}], x_axis="x"))
    assert not is_time_axis(_bar([{"class": "Forest"}], x_axis="class"))


def test_time_facts_of_a_measure_other_than_area():
    chart = _bar(
        [
            {"year": 2001, "carbon_emissions_MgCO2e": 10.0},
            {"year": 2002, "carbon_emissions_MgCO2e": 30.0},
            {"year": 2003, "carbon_emissions_MgCO2e": None},
            {"year": 2004, "carbon_emissions_MgCO2e": 5.0},
        ],
        y_axis="carbon_emissions_MgCO2e",
    )

    facts = measure_facts(chart)

    m = "carbon_emissions_MgCO2e"
    assert facts == [
        Fact("total", m, "MgCO2e", 45.0, "2001", "2004"),
        Fact("max", m, "MgCO2e", 30.0, "2002"),
        Fact("min", m, "MgCO2e", 5.0, "2004"),
        Fact("change", m, "MgCO2e", -5.0, "2001", "2004", share=-50.0),
    ]
    assert [f.sentence for f in facts] == [
        f"Total {m} from 2001 to 2004: 45 MgCO2e.",
        f"Largest {m}: 30 MgCO2e in 2002.",
        f"Smallest {m}: 5 MgCO2e in 2004.",
        f"Change of {m} from 2001 to 2004: -5 MgCO2e (-50%).",
    ]


def test_ties_keep_the_earlier_year_and_a_zero_start_has_no_percent():
    chart = _bar(
        [
            {"year": 2001, "area_ha": 0.0},
            {"year": 2002, "area_ha": 7.0},
            {"year": 2003, "area_ha": 7.0},
        ]
    )

    facts = {f.kind: f for f in measure_facts(chart)}

    assert facts["max"].x == "2002"
    assert facts["min"].x == "2001"
    assert facts["change"].share is None
    assert facts["change"].sentence == (
        "Change of area_ha from 2001 to 2003: +7 ha."
    )


def test_one_year_has_no_change():
    facts = measure_facts(_bar([{"year": 2020, "area_ha": 2.0}]))

    assert [f.kind for f in facts] == ["total", "max", "min"]


def test_class_facts_rank_with_shares():
    chart = _bar(
        [
            {"driver": "Logging", "area_ha": 25.0},
            {"driver": "Wildfire", "area_ha": 75.0},
        ],
        x_axis="driver",
    )

    facts = measure_facts(chart)

    assert facts[0] == Fact("total", "area_ha", "ha", 100.0)
    assert facts[0].sentence == "Total area_ha: 100 ha."
    assert facts[1].sentence == (
        "Rank 1 of area_ha: Wildfire, 75 ha, 75% of the total."
    )
    assert facts[2].rank == 2 and facts[2].x == "Logging"


def test_negative_values_get_no_share():
    chart = _bar(
        [
            {"flux": "Emissions", "value_MgCO2e": 10.0},
            {"flux": "Removals", "value_MgCO2e": -4.0},
        ],
        x_axis="flux",
        y_axis="value_MgCO2e",
    )

    ranks = [f for f in measure_facts(chart) if f.kind == "rank"]

    assert all(f.share is None for f in ranks)


def test_stacked_series_get_facts_each_and_a_total():
    chart = _bar(
        [
            {"year": 2021, "fires_ha": 1.0, "other_ha": 2.0},
            {"year": 2022, "fires_ha": 3.0, "other_ha": None},
        ],
        series=["fires_ha", "other_ha"],
    )

    facts = measure_facts(chart)

    totals = [f for f in facts if f.kind == "total"]
    assert [(f.measure, f.value) for f in totals] == [
        ("fires_ha", 4.0),
        ("other_ha", 2.0),
        ("all series", 6.0),
    ]
