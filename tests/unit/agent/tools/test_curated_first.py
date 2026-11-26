"""Curated charts first: the gate in `Analyst.analyze`, the caption, the
tool message, and the profile flag (docs/curated-charts-first-plan.md)."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.agent.agent_config import (
    DEFAULT_PROFILE,
    default_registry,
)
from src.agent.datasets.handlers.analytics_handler import (
    DEFAULT_CANOPY_COVER,
    FOREST_CARBON_FLUX_ID,
    GRASSLANDS_ID,
    NATURAL_FOREST_DEFAULT_CANOPY_COVER,
    SLUC_EMISSION_FACTORS_ID,
    TREE_COVER_LOSS_BY_DRIVER_ID,
    TREE_COVER_LOSS_ID,
)
from src.agent.skills.loader import get_skill, render_body
from src.agent.subagents.analyst import tool as analyst_tool
from src.agent.subagents.analyst.charts.model import InsightChart
from src.agent.subagents.analyst.curated_first import (
    CURATED_ANSWER_INSTRUCTION,
    MAX_MESSAGE_ROWS,
    build_curated_tool_message,
    chart_fact_sentences,
    curated_caption,
    curated_facts_text,
    format_rows,
    period_label,
    unshown_columns,
)
from src.agent.subagents.analyst.tool import (
    SPEC,
    Analyst,
)

# Invented figures with decimals that a 16-character cut would change.
TCL_ROWS = [
    (2021, 1234.5678901234567, 456789.12345678901),
    (2022, 2345.6789012345678, 567890.12345678901),
    (2023, 345.67890123456789, 67890.123456789012),
]


def _tcl_data(areas=("BRA.14",), emissions=True):
    data: dict[str, list] = {
        "aoi_id": [],
        "name": [],
        "tree_cover_loss_year": [],
        "area_ha": [],
        "carbon_emissions_MgCO2e": [],
    }
    for area in areas:
        for year, loss, carbon in TCL_ROWS:
            data["aoi_id"].append(area)
            data["name"].append(f"Area {area}")
            data["tree_cover_loss_year"].append(year)
            data["area_ha"].append(loss)
            data["carbon_emissions_MgCO2e"].append(
                carbon if emissions else None
            )
    return data


def _statistics(
    aoi_names=("Pará",),
    dataset_id=TREE_COVER_LOSS_ID,
    context_layer=None,
    parameters=None,
    canopy_cover=DEFAULT_CANOPY_COVER,
    aoi_ids=None,
):
    return {
        "id": str(uuid4()),
        "dataset_id": dataset_id,
        "dataset_name": "Tree cover loss",
        "start_date": "2021-01-01",
        "end_date": "2023-12-31",
        "source_url": "https://analytics.example.com/result/tcl",
        "aoi_names": list(aoi_names),
        "aoi_ids": list(aoi_ids)
        if aoi_ids is not None
        else [f"id-{i}" for i, _ in enumerate(aoi_names)],
        "aoi_sources": ["gadm"] * len(aoi_names),
        "context_layer": context_layer,
        "parameters": parameters,
        # What the pull sent, as pull_data stores it.
        "canopy_cover": canopy_cover,
    }


def _content(command):
    return command.update["messages"][0].content


class _Executor(Exception):
    """Raised in place of the code executor path."""


@pytest.fixture
def run():
    """Patch I/O. `run.data` is the pulled data. The code executor path
    raises `_Executor`, so a test sees which path ran."""
    persist = AsyncMock(return_value="insight-1")
    state = type("Run", (), {})()
    state.persist = persist
    state.data = _tcl_data()

    async def load(_statistics):
        return state.data

    with (
        patch.object(analyst_tool, "_load_statistics_data", load),
        patch.object(analyst_tool, "persist_insight", persist),
        patch.object(analyst_tool, "current_user_id", return_value="user-1"),
        patch.object(
            Analyst, "_resolve_charts", AsyncMock(side_effect=_Executor)
        ),
        patch.object(
            analyst_tool,
            "InsightTextGenerator",
            side_effect=AssertionError("text generator must not run"),
        ),
    ):
        yield state


async def _analyze(statistics, chart="standard", query="tree cover loss"):
    return await Analyst().analyze(
        query,
        statistics=[statistics],
        tool_call_id="call-1",
        language="en",
        chart=chart,
    )


# --- the gate ---------------------------------------------------------------


async def test_one_area_gets_the_curated_charts(run):
    command = await _analyze(_statistics())

    update = command.update
    assert update["insight_id"] == "insight-1"
    assert update["follow_up_suggestions"] == []
    assert update["codeact_parts"] == []
    assert len(update["charts_data"]) == 2
    assert update["messages"][0].status == "success"
    insight = run.persist.await_args.args[0]
    assert [c.view_id for c in insight.charts] == [
        "tcl.annual_loss",
        "tcl.annual_emissions",
    ]
    assert [c.position for c in insight.charts] == [0, 1]
    assert run.persist.await_args.kwargs["codeact_parts"] == []


async def test_state_has_the_fields_of_the_code_executor_path(run):
    command = await _analyze(_statistics())

    assert set(command.update) == {
        "insight_id",
        "analysis_inputs",
        "insight",
        "follow_up_suggestions",
        "codeact_parts",
        "charts_data",
        "messages",
    }


async def test_several_areas_get_the_two_rankings(run):
    run.data = _tcl_data(areas=("BRA.14", "BRA.13"))

    command = await _analyze(
        _statistics(
            aoi_names=("Pará, Brazil", "Mato Grosso, Brazil"),
            aoi_ids=("BRA.14_1", "BRA.13_1"),
        )
    )

    insight = run.persist.await_args.args[0]
    # The loss ranking is first, as the annual loss is for one area.
    assert [c.view_id for c in insight.charts] == [
        "tcl.loss_ranking",
        "tcl.emissions_ranking",
    ]
    assert [c.position for c in insight.charts] == [0, 1]
    assert [c["type"] for c in command.update["charts_data"]] == [
        "ranked-bar",
        "ranked-bar",
    ]
    loss = insight.charts[0]
    # Three years of the same figures for each area: a tie.
    assert [
        (r["rank"], r["aoi_id"], r["parent"]) for r in loss.chart_data
    ] == [
        (1, "BRA.13", "Brazil"),
        (1, "BRA.14", "Brazil"),
    ]


async def test_several_areas_of_a_dataset_with_no_ranking_go_to_the_code_executor(
    run,
):
    run.data = _tcl_data(areas=("BRA.14", "BRA.13"))

    with pytest.raises(_Executor):
        await _analyze(
            _statistics(
                aoi_names=("Pará", "Mato Grosso"),
                dataset_id=TREE_COVER_LOSS_BY_DRIVER_ID,
            )
        )


async def test_a_ranking_of_rows_with_an_unknown_area_goes_to_the_code_executor(
    run,
):
    run.data = _tcl_data(areas=("BRA.14", "BRA.99"))

    # The failure is loud: the analyst logs it with its traceback (an
    # error-level record) before it falls back.
    with patch.object(analyst_tool.logger, "exception") as log_exception:
        with pytest.raises(_Executor):
            await _analyze(
                _statistics(
                    aoi_names=("Pará", "Mato Grosso"),
                    aoi_ids=("BRA.14_1", "BRA.13_1"),
                )
            )
    log_exception.assert_called_once()
    run.persist.assert_not_awaited()


async def test_a_pull_with_no_loss_in_any_area_goes_to_the_code_executor(run):
    run.data = {
        "aoi_id": ["BRA.14", "BRA.13"],
        "name": ["Pará", "Mato Grosso"],
        "tree_cover_loss_year": [2021, 2021],
        "area_ha": [0, 0],
        "carbon_emissions_MgCO2e": [0, 0],
    }

    with pytest.raises(_Executor):
        await _analyze(
            _statistics(
                aoi_names=("Pará", "Mato Grosso"),
                aoi_ids=("BRA.14_1", "BRA.13_1"),
            )
        )


async def test_area_count_comes_from_the_rows(run):
    # One area in state, two in the rows: the rows decide.
    run.data = _tcl_data(areas=("BRA.14", "BRA.13"))

    with pytest.raises(_Executor):
        await _analyze(_statistics())


async def test_empty_rows_go_to_the_code_executor(run):
    run.data = {}

    with pytest.raises(_Executor):
        await _analyze(_statistics())


async def test_custom_goes_to_the_code_executor(run):
    with pytest.raises(_Executor):
        await _analyze(_statistics(), chart="custom")


async def test_no_chart_argument_goes_to_the_code_executor(run):
    # The default profile: no curated chart, as before.
    with pytest.raises(_Executor):
        await _analyze(_statistics(), chart=None)


async def test_a_dataset_without_an_agent_view_goes_to_the_code_executor(run):
    with pytest.raises(_Executor):
        await _analyze(_statistics(dataset_id=SLUC_EMISSION_FACTORS_ID))


async def test_a_context_layer_keeps_the_curated_chart(run):
    command = await _analyze(_statistics(context_layer="primary_forest"))

    assert command.update["insight"] == (
        "Standard Tree cover loss charts for Pará, 2021–2023 "
        "(primary forest, canopy cover ≥ 30%)."
    )
    assert "Context layer: primary forest" in _content(command)
    insight = run.persist.await_args.args[0]
    assert [c.title for c in insight.charts] == [
        "Annual Tree Cover Loss (primary forest)",
        "Annual GHG Emissions from Tree Cover Loss (primary forest)",
    ]


async def test_no_context_layer_keeps_the_plain_title(run):
    await _analyze(_statistics())

    insight = run.persist.await_args.args[0]
    assert insight.charts[0].title == "Annual Tree Cover Loss"


async def test_rows_keep_the_drawn_columns_and_the_message_names_the_rest(run):
    command = await _analyze(_statistics())

    insight = run.persist.await_args.args[0]
    for chart in insight.charts:
        assert {k for row in chart.chart_data for k in row} == {
            chart.x_axis,
            chart.y_axis,
        }
    assert (
        "Columns of the pulled data that no chart shows: aoi_id, name"
        in _content(command)
    )


async def test_a_chart_with_no_data_is_left_out(run):
    # Natural forest below a 30% threshold: the API computes no emissions.
    run.data = _tcl_data(emissions=False)

    command = await _analyze(
        _statistics(
            context_layer="natural_forest",
            canopy_cover=NATURAL_FOREST_DEFAULT_CANOPY_COVER,
        )
    )

    insight = run.persist.await_args.args[0]
    assert [c.view_id for c in insight.charts] == ["tcl.annual_loss"]
    assert len(command.update["charts_data"]) == 1
    assert "carbon_emissions" not in _content(command)


async def test_the_gate_reads_the_latest_pull_only(run):
    older = _statistics(dataset_id=GRASSLANDS_ID)
    latest = _statistics()

    await Analyst().analyze(
        "tree cover loss",
        statistics=[older, latest],
        tool_call_id="call-1",
        language="en",
        chart="standard",
    )

    assert run.persist.await_args.kwargs["statistics_ids"] == [latest["id"]]
    assert run.persist.await_args.kwargs["statistics_ids_exact"] is True


async def test_a_curated_chart_records_the_latest_pull_only(run):
    older = _statistics(dataset_id=GRASSLANDS_ID)
    latest = {
        **_statistics(),
        "aoi_ids": ["BRA.14_1"],
        "aoi_sources": ["gadm"],
    }

    command = await Analyst().analyze(
        "tree cover loss",
        statistics=[older, latest],
        tool_call_id="call-1",
        language="en",
        chart="standard",
    )

    expected = [
        {
            "areas": [
                {"name": "Pará", "source": "gadm", "src_id": "BRA.14_1"}
            ],
            "dataset_id": TREE_COVER_LOSS_ID,
            "dataset_name": "Tree cover loss",
            "pulled_start_date": "2021-01-01",
            "pulled_end_date": "2023-12-31",
            "canopy_cover": DEFAULT_CANOPY_COVER,
            "context_layer": None,
        }
    ]
    assert command.update["analysis_inputs"] == expected


async def test_a_curated_pull_without_an_id_records_no_inputs(run):
    old = _statistics()
    del old["id"]

    command = await Analyst().analyze(
        "tree cover loss",
        statistics=[old],
        tool_call_id="call-1",
        language="en",
        chart="standard",
    )

    # The API reports null for links that are not exact, so the stream does.
    assert run.persist.await_args.kwargs["statistics_ids"] == []
    assert run.persist.await_args.kwargs["statistics_ids_exact"] is False
    assert command.update["analysis_inputs"] is None


async def test_a_curated_chart_records_the_threshold_its_caption_states(run):
    command = await _analyze(
        _statistics(
            context_layer="natural_forest",
            canopy_cover=NATURAL_FOREST_DEFAULT_CANOPY_COVER,
        )
    )

    (entry,) = command.update["analysis_inputs"]
    assert entry["canopy_cover"] == NATURAL_FOREST_DEFAULT_CANOPY_COVER
    assert entry["context_layer"] == "natural_forest"
    caption = run.persist.await_args.args[0].primary_insight
    threshold = NATURAL_FOREST_DEFAULT_CANOPY_COVER
    assert f"canopy cover ≥ {threshold}%" in caption


# --- caption ----------------------------------------------------------------


async def test_caption_without_a_context_layer_states_the_threshold():
    caption = await curated_caption(_statistics(), "en")

    assert caption == (
        "Standard Tree cover loss charts for Pará, 2021–2023 "
        "(canopy cover ≥ 30%)."
    )


async def test_caption_of_natural_forest_states_its_default_threshold():
    caption = await curated_caption(
        _statistics(context_layer="natural_forest"), "en"
    )

    assert "(natural forest, canopy cover ≥ 10%)" in caption


async def test_caption_states_a_selected_threshold():
    caption = await curated_caption(
        _statistics(
            parameters=[{"name": "canopy_cover", "values": [50]}],
        ),
        "en",
    )

    assert "canopy cover ≥ 50%" in caption


async def test_caption_is_localised_and_has_no_figures():
    caption = await curated_caption(
        _statistics(context_layer="primary_forest"), "es"
    )

    assert caption == (
        "Gráficos estándar de Tree cover loss para Pará, 2021–2023 "
        "(bosque primario, cobertura de copa ≥ 30%)."
    )


async def test_caption_of_a_dataset_without_a_threshold():
    caption = await curated_caption(
        _statistics(dataset_id=GRASSLANDS_ID), "en"
    )

    assert caption.endswith("Pará, 2021–2023.")


def test_period_label():
    assert period_label("2001-01-01", "2025-12-31") == "2001–2025"
    assert period_label("2024-01-01", "2024-12-31") == "2024"
    assert period_label("2024-06-01", "2025-05-31") == (
        "2024-06-01 – 2025-05-31"
    )


# --- tool message -----------------------------------------------------------


async def test_tool_message_has_header_rows_facts_instruction(run):
    command = await _analyze(_statistics())
    content = _content(command)

    # Header.
    assert "Standard charts shown to the user: 2." in content
    assert "(view tcl.annual_loss)" in content
    assert "Area: Pará" in content
    assert "Pulled period: 2021-01-01 to 2023-12-31" in content
    assert "Years or dates with data in the rows: 2021 to 2023" in content
    assert "Context layer: none" in content
    assert "Canopy cover threshold: 30%" in content
    # Rows in full precision, with units.
    assert "tree_cover_loss_year | area_ha (ha)" in content
    assert f"2021 | {TCL_ROWS[0][1]!r}" in content
    assert f"2022 | {TCL_ROWS[1][2]!r}" in content
    # Facts.
    assert "Total area_ha from 2021 to 2023: 3925.93 ha." in content
    assert "Largest area_ha: 2345.68 ha in 2022." in content
    assert "Smallest area_ha: 345.68 ha in 2023." in content
    assert "Change of area_ha from 2021 to 2023: -888.89 ha (-72.00%)." in (
        content
    )
    assert "MgCO2e" in content
    # The catalog cautions (the dataset can come from a UI selection, with
    # no pick_dataset message); the instruction is last.
    assert "Dataset cautions:" in content
    assert content.endswith(CURATED_ANSWER_INSTRUCTION)


def test_tool_message_without_cautions():
    chart = InsightChart(
        position=0,
        title="Loss",
        chart_type="bar",
        x_axis="year",
        y_axis="area_ha",
        chart_data=[{"year": 2020, "area_ha": 1.5}],
        view_id="tcl.annual_loss",
    )

    content = build_curated_tool_message([chart], _statistics(), "caption")

    assert "Dataset cautions" not in content
    assert "Caption shown under the chart: caption" in content


def test_a_large_chart_lists_no_rows():
    chart = InsightChart(
        position=0,
        title="Alerts",
        chart_type="bar",
        x_axis="date",
        y_axis="area_ha",
        chart_data=[
            {"date": f"day-{i}", "area_ha": 1.0}
            for i in range(MAX_MESSAGE_ROWS + 1)
        ],
    )

    assert format_rows(chart) == (
        f"{MAX_MESSAGE_ROWS + 1} rows; too many to list. Use the facts."
    )


# --- the generate_insights tool ---------------------------------------------


def test_generate_insights_has_the_chart_argument():
    schema = SPEC.tool.tool_call_schema.model_json_schema()

    assert schema["properties"]["chart"]["enum"] == ["standard", "custom"]
    assert schema["properties"]["chart"]["default"] == "standard"
    for profile in (DEFAULT_PROFILE, "base", "experimental", "lgms"):
        config = default_registry.resolve(profile)
        spec = next(
            s for s in config.specs if s.tool.name == "generate_insights"
        )
        assert spec is SPEC
        assert 'chart="standard"' in config.tool_descriptions()


def test_analyze_skill_has_the_chart_guidance():
    body = render_body(get_skill("analyze"), frozenset())

    assert "<!--" not in body
    assert 'chart="custom"' in body
    assert "send that period to `pull_data`" in body


async def test_tool_passes_the_chart_argument():
    with patch.object(
        Analyst, "analyze", AsyncMock(return_value="done")
    ) as analyze:
        result = await SPEC.tool.coroutine(
            "query", chart="custom", state={"statistics": []}
        )

    assert result == "done"
    assert analyze.await_args.kwargs["chart"] == "custom"


# --- tree cover loss by driver (phase 1b) ----------------------------------


def _driver_data():
    drivers = [
        ("Shifting cultivation", 273519.47),
        ("Logging", 71485.15),
        ("Permanent agriculture", 64953.81),
        ("Hard commodities", 22206.13),
        ("Unknown", 20169.0),
        ("Settlements and infrastructure", 5429.56),
    ]
    return {
        "aoi_id": ["GAB"] * len(drivers),
        "aoi_type": ["admin"] * len(drivers),
        "name": ["Gabon"] * len(drivers),
        "tree_cover_loss_driver": [d for d, _ in drivers],
        "area_ha": [a for _, a in drivers],
        "carbon_emissions_MgCO2e": [a * 600 for _, a in drivers],
    }


async def test_drivers_get_the_curated_pie_with_its_note_and_facts(run):
    run.data = _driver_data()
    statistics = _statistics(
        aoi_names=("Gabon",), dataset_id=TREE_COVER_LOSS_BY_DRIVER_ID
    )
    statistics["start_date"], statistics["end_date"] = (
        "2001-01-01",
        "2025-12-31",
    )

    # The selector can set "driver", which is not a context layer.
    statistics["context_layer"] = "driver"

    command = await _analyze(statistics)

    insight = run.persist.await_args.args[0]
    assert [c.view_id for c in insight.charts] == ["tcl_by_driver.by_driver"]
    assert insight.charts[0].title == "Tree Cover Loss by Dominant Driver"
    assert "(driver" not in command.update["insight"]
    assert "Context layer: none (all of the area)" in _content(command)
    (chart,) = insight.charts
    assert all(
        set(row) == {"tree_cover_loss_driver", "area_ha"}
        for row in chart.chart_data
    )
    content = _content(command)
    assert (
        "Chart 1 note: The drivers cover the whole period 2001 to 2025."
        in content
    )
    assert "- Unknown driver, not in the chart: 20169 ha." in content
    assert (
        "- Group deforestation proxy (permanent agriculture, hard commodities, "
        "settlements and infrastructure): 92589.50 ha" in content
    )
    assert (
        "Columns of the pulled data that no chart shows: aoi_id, aoi_type, "
        "name, carbon_emissions_MgCO2e" in content
    )


# --- review fixes -----------------------------------------------------------


async def test_an_error_after_the_fetch_goes_to_the_code_executor(run):
    # An alert tier or a driver column that a generator does not know.
    with patch(
        "src.api.services.charts.tcl.TCLChartGenerator.generate",
        side_effect=ValueError("Unknown alert confidence: 'medium'"),
    ):
        with pytest.raises(_Executor):
            await _analyze(_statistics())
    run.persist.assert_not_awaited()


async def test_an_error_in_the_caption_goes_to_the_code_executor(run):
    with patch(
        "src.agent.subagents.analyst.curated_first.t",
        AsyncMock(side_effect=RuntimeError("translation failed")),
    ):
        with pytest.raises(_Executor):
            await _analyze(_statistics())
    run.persist.assert_not_awaited()


async def test_a_requested_area_with_no_rows_still_counts(run):
    # Two areas asked for, rows for one: not a one-area chart.
    with pytest.raises(_Executor):
        await _analyze(_statistics(aoi_names=("Pará", "Amapá")))


async def test_years_without_loss_are_zero_in_the_chart_and_the_facts(run):
    run.data = {
        "aoi_id": ["BRA.14"] * 3,
        "tree_cover_loss_year": [2003, 2010, 2019],
        "area_ha": [5.0, 2.0, 8.0],
        "carbon_emissions_MgCO2e": [50.0, 20.0, 80.0],
    }
    statistics = _statistics()
    statistics["start_date"], statistics["end_date"] = (
        "2001-01-01",
        "2024-12-31",
    )

    command = await _analyze(statistics)

    insight = run.persist.await_args.args[0]
    years = [r["tree_cover_loss_year"] for r in insight.charts[0].chart_data]
    assert years == list(range(2001, 2025))
    content = _content(command)
    assert "Total area_ha from 2001 to 2024: 15 ha." in content
    assert "Smallest area_ha: 0 ha in 2001." in content
    assert "Years or dates with data in the rows: 2001 to 2024" in content


def _flux_data():
    return {
        "aoi_id": ["BRA.14"],
        "aoi_type": ["admin"],
        "carbon_gross_emissions_Mg_CO2e": [311.5],
        "carbon_gross_removals_Mg_CO2e": [1762.0],
        "carbon_net_flux_Mg_CO2e": [-1450.5],
    }


async def test_a_dataset_without_dates_states_the_period_of_its_data(run):
    run.data = _flux_data()
    statistics = _statistics(dataset_id=FOREST_CARBON_FLUX_ID)
    statistics["dataset_name"] = "Forest greenhouse gas net flux"
    statistics["start_date"], statistics["end_date"] = (
        "2015-01-01",
        "2020-12-31",
    )

    command = await _analyze(statistics, query="is Pará a carbon sink")

    assert "2001–2025" in command.update["insight"]
    assert "2015" not in command.update["insight"]
    content = _content(command)
    assert "Period of the data: 2001-01-01 to 2025-12-31." in content
    assert "Requested period: 2015-01-01 to 2020-12-31." in content
    # The chart pivots the three flux columns: they are drawn.
    assert "carbon_net_flux_Mg_CO2e" not in content.split("no chart shows")[-1]


# --- the ranking of areas ---------------------------------------------------


def _ranking_chart(rows, y_axis="area_ha", view_id="tcl.loss_ranking"):
    return InsightChart(
        title="Tree Cover Loss by Area",
        chart_type="ranked-bar",
        x_axis="name",
        y_axis=y_axis,
        chart_data=rows,
        view_id=view_id,
    )


def _ranked_row(rank, name, value, parent="Kenya", share=None, area_id=None):
    row = {
        "rank": rank,
        "aoi_id": area_id or f"KEN.{rank}",
        "name": name,
        "parent": parent,
        "area_ha": value,
    }
    if share is not None:
        row["share_pct"] = share
    return row


def test_ranking_rows_have_rank_name_value_and_share():
    chart = _ranking_chart(
        [
            _ranked_row(1, "Narok", 72050.31, share=60.0),
            _ranked_row(2, "Nakuru", 36210.04, share=30.0),
            _ranked_row(3, "Nairobi", 0, share=0.0),
        ]
    )

    assert format_rows(chart).splitlines() == [
        "rank | name | area_ha (ha) | share_pct (%)",
        "1 | Narok | 72050.31 | 60",
        "2 | Nakuru | 36210.04 | 30",
        "3 | Nairobi | 0 | 0",
    ]


def test_ranking_rows_name_the_parent_of_a_repeated_name_only():
    chart = _ranking_chart(
        [
            _ranked_row(1, "Bom Jesus", 9, "Piauí", area_id="BRA.1.1"),
            _ranked_row(
                2, "Bom Jesus", 5, "Rio Grande do Sul", area_id="BRA.2.1"
            ),
            _ranked_row(3, "Belém", 1, "Pará", area_id="BRA.3.1"),
        ]
    )

    lines = format_rows(chart).splitlines()

    assert lines[1] == "1 | Bom Jesus · Piauí | 9"
    assert lines[2] == "2 | Bom Jesus · Rio Grande do Sul | 5"
    assert lines[3] == "3 | Belém | 1"


def test_ranking_rows_without_shares_have_no_share_column():
    chart = _ranking_chart([_ranked_row(1, "A", 2), _ranked_row(2, "B", 1)])

    assert format_rows(chart).splitlines()[0] == "rank | name | area_ha (ha)"


def test_a_ranking_over_the_row_cap_counts_the_rest():
    rows = [
        _ranked_row(rank, f"Area {rank}", 1000 - rank, area_id=f"X.{rank}")
        for rank in range(1, MAX_MESSAGE_ROWS + 31)
    ]

    lines = format_rows(_ranking_chart(rows)).splitlines()

    assert len(lines) == 1 + MAX_MESSAGE_ROWS + 1
    assert lines[-2].startswith(
        f"{MAX_MESSAGE_ROWS} | Area {MAX_MESSAGE_ROWS} |"
    )
    assert lines[-1] == "30 more areas, each with less"


def test_a_tie_at_the_row_cap_does_not_say_less():
    rows = [
        _ranked_row(1, f"Area {i}", 5.0, area_id=f"X.{i}")
        for i in range(MAX_MESSAGE_ROWS + 2)
    ]

    assert format_rows(_ranking_chart(rows)).endswith(
        "2 more areas, each with the same or less"
    )


def test_ranking_facts_give_the_count_the_total_and_the_empty_areas():
    chart = _ranking_chart(
        [
            _ranked_row(1, "Narok", 75.0, share=75.0),
            _ranked_row(2, "Nakuru", 25.0, share=25.0),
            _ranked_row(3, "Nairobi", 0, share=0.0),
            _ranked_row(3, "Mombasa", 0, share=0.0),
        ]
    )

    assert chart_fact_sentences(chart) == [
        "4 areas ranked by area_ha (ha), largest first. Areas with the same "
        "value share a rank.",
        "Total over the 4 areas: 100 ha. A share is the percent of this "
        "total.",
        "2 areas with a value of 0 for area_ha (ha): Nairobi, Mombasa.",
    ]


def test_ranking_facts_without_shares_give_no_total():
    chart = _ranking_chart([_ranked_row(1, "A", 2), _ranked_row(2, "B", 1)])

    facts = chart_fact_sentences(chart)

    assert len(facts) == 2
    assert facts[1].startswith("No total and no share are given")


def test_many_empty_areas_are_counted_not_named():
    rows = [_ranked_row(1, "Big", 9.0, share=100.0)] + [
        _ranked_row(2, f"Empty {i}", 0, share=0.0, area_id=f"X.{i}")
        for i in range(21)
    ]

    facts = chart_fact_sentences(_ranking_chart(rows))

    assert facts[-1] == "21 areas with a value of 0 for area_ha (ha)."


def test_a_restyled_ranking_keeps_its_ranking_facts():
    # update_insight_display keeps the view and the rows and changes the type.
    chart = _ranking_chart([_ranked_row(1, "A", 2), _ranked_row(2, "B", 1)])
    chart.chart_type = "bar"

    assert chart_fact_sentences(chart)[0].startswith("2 areas ranked by")
    assert format_rows(chart).startswith("rank | name")


def test_a_saved_ranking_gives_its_facts_on_a_recall():
    chart = _ranking_chart(
        [
            _ranked_row(1, "A", 3.0, share=75.0),
            _ranked_row(2, "B", 1.0, share=25.0),
        ]
    )
    chart.dataset_id = TREE_COVER_LOSS_ID

    text = curated_facts_text([chart])

    assert text.startswith(
        "Facts of Tree Cover Loss by Area (computed in code):"
    )
    assert "- Total over the 2 areas: 4 ha." in text


def test_the_ranking_chart_does_not_list_the_columns_that_it_consumes():
    rows = [
        {
            "aoi_id": "KEN.1",
            "aoi_type": "admin",
            "name": "Baringo",
            "tree_cover_loss_year": 2024,
            "area_ha": 3.0,
            "carbon_emissions_MgCO2e": 30.0,
        },
        {
            "aoi_id": "KEN.2",
            "aoi_type": "admin",
            "name": "Bomet",
            "tree_cover_loss_year": 2024,
            "area_ha": 9.0,
            "carbon_emissions_MgCO2e": 20.0,
        },
    ]
    pair = [
        _ranking_chart(
            [{"tree_cover_loss_year": 2024, "area_ha": 3.0}],
            view_id="tcl.annual_loss",
        ),
        _ranking_chart(
            [{"tree_cover_loss_year": 2024, "carbon_emissions_MgCO2e": 3.0}],
            view_id="tcl.annual_emissions",
        ),
    ]
    ranking = [
        _ranking_chart([_ranked_row(1, "A", 2.0)]),
        _ranking_chart(
            [
                {
                    **_ranked_row(1, "A", 2.0),
                    "carbon_emissions_MgCO2e": 1.0,
                }
            ],
            y_axis="carbon_emissions_MgCO2e",
            view_id="tcl.emissions_ranking",
        ),
    ]

    # For the pair the year is drawn; the ranking sums it, so only the
    # year differs. aoi_type is listed for both.
    assert unshown_columns(rows, pair) == [
        "aoi_id",
        "aoi_type",
        "name",
    ]
    assert unshown_columns(rows, ranking) == ["aoi_type"]


async def test_the_tool_message_of_a_ranking_has_rows_facts_and_the_note(run):
    run.data = _tcl_data(areas=("BRA.14", "BRA.13"))
    # A different total for the second area: three years of 100 more.
    run.data["area_ha"][3:] = [v + 100 for v in run.data["area_ha"][3:]]

    command = await _analyze(
        _statistics(
            aoi_names=("Pará, Brazil", "Mato Grosso, Brazil"),
            aoi_ids=("BRA.14_1", "BRA.13_1"),
        )
    )
    content = _content(command)

    assert "Standard charts shown to the user: 2." in content
    assert (
        "Chart 1: Tree Cover Loss by Area (view tcl.loss_ranking)" in content
    )
    assert "Chart 1 note: Each bar is the total tree cover loss" in content
    assert (
        "Chart 1 rows:\nrank | name | area_ha (ha) | share_pct (%)" in content
    )
    assert "1 | Mato Grosso |" in content
    assert "Chart 1 facts (computed in code):\n- 2 areas ranked by" in content
    assert "Total over the 2 areas:" in content
    # The year is summed away, not an unshown column.
    assert (
        "tree_cover_loss_year"
        not in content.split("Columns of the pulled")[-1]
    )
