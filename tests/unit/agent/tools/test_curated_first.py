"""Curated charts first: the gate in `Analyst.analyze`, the caption, the
tool message, and the profile flag (docs/curated-charts-first-plan.md)."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.agent.agent_config import (
    CURATED_CHARTS_FIRST,
    CURATED_CHARTS_PROFILE,
    DEFAULT_PROFILE,
    default_registry,
)
from src.agent.datasets.handlers.analytics_handler import (
    GRASSLANDS_ID,
    TREE_COVER_LOSS_ID,
)
from src.agent.skills.loader import get_skill, render_body
from src.agent.subagents.analyst import tool as analyst_tool
from src.agent.subagents.analyst.charts.model import InsightChart
from src.agent.subagents.analyst.curated_first import (
    CURATED_ANSWER_INSTRUCTION,
    MAX_MESSAGE_ROWS,
    build_curated_tool_message,
    curated_caption,
    format_rows,
    period_label,
)
from src.agent.subagents.analyst.tool import (
    CURATED_FIRST_SPEC,
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
):
    return {
        "id": str(uuid4()),
        "dataset_id": dataset_id,
        "dataset_name": "Tree cover loss",
        "start_date": "2021-01-01",
        "end_date": "2023-12-31",
        "source_url": "https://analytics.example.com/result/tcl",
        "aoi_names": list(aoi_names),
        "aoi_ids": [f"id-{i}" for i, _ in enumerate(aoi_names)],
        "context_layer": context_layer,
        "parameters": parameters,
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
        "insight",
        "follow_up_suggestions",
        "codeact_parts",
        "charts_data",
        "messages",
    }


async def test_several_areas_go_to_the_code_executor(run):
    run.data = _tcl_data(areas=("BRA.14", "BRA.13"))

    with pytest.raises(_Executor):
        await _analyze(_statistics(aoi_names=("Pará", "Mato Grosso")))


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
        await _analyze(_statistics(dataset_id=GRASSLANDS_ID))


async def test_a_context_layer_keeps_the_curated_chart(run):
    command = await _analyze(_statistics(context_layer="primary_forest"))

    assert command.update["insight"] == (
        "Standard Tree cover loss charts for Pará, 2021–2023 "
        "(primary forest, canopy cover ≥ 30%)."
    )
    assert "Context layer: primary forest" in _content(command)


async def test_a_chart_with_no_data_is_left_out(run):
    # Natural forest below a 30% threshold: the API computes no emissions.
    run.data = _tcl_data(emissions=False)

    command = await _analyze(_statistics(context_layer="natural_forest"))

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


async def test_tool_message_has_header_rows_facts_cautions_instruction(run):
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
    # Cautions, then the instruction last.
    assert "Dataset cautions:" in content
    assert "does not equate to deforestation" in content
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


# --- profile flag -----------------------------------------------------------


def _generate_insights_spec(profile):
    config = default_registry.resolve(profile)
    return next(s for s in config.specs if s.tool.name == "generate_insights")


def test_default_profile_keeps_the_generate_insights_tool():
    spec = _generate_insights_spec(DEFAULT_PROFILE)

    assert spec is SPEC
    schema = spec.tool.tool_call_schema.model_json_schema()
    assert "chart" not in schema["properties"]
    assert default_registry.resolve(DEFAULT_PROFILE).flags == frozenset()
    assert (
        'chart="standard"'
        not in default_registry.resolve(DEFAULT_PROFILE).tool_descriptions()
    )


def test_curated_profile_has_the_chart_argument():
    spec = _generate_insights_spec(CURATED_CHARTS_PROFILE)

    assert spec is CURATED_FIRST_SPEC
    schema = spec.tool.tool_call_schema.model_json_schema()
    assert schema["properties"]["chart"]["enum"] == ["standard", "custom"]
    assert schema["properties"]["chart"]["default"] == "standard"
    config = default_registry.resolve(CURATED_CHARTS_PROFILE)
    assert config.availability().flags == {CURATED_CHARTS_FIRST}
    assert 'chart="standard"' in config.tool_descriptions()


def test_curated_profile_keeps_the_default_surface():
    default = default_registry.resolve(DEFAULT_PROFILE)
    curated = default_registry.resolve(CURATED_CHARTS_PROFILE)

    assert curated.skills == default.skills
    assert curated.tool_names() == default.tool_names()
    assert curated.excluded_datasets == default.excluded_datasets


def test_analyze_skill_by_flag():
    skill = get_skill("analyze")
    default = render_body(skill, frozenset())
    flagged = render_body(skill, frozenset({CURATED_CHARTS_FIRST}))

    for body in (default, flagged):
        assert "<!--" not in body
    assert "chart=" not in default
    assert (
        "after a successful pull, always run this to produce one chart insight.\n"
        in default
    )
    assert 'chart="custom"' in flagged
    assert "send that period to `pull_data`" in flagged
    assert "send that period" not in default


async def test_tool_variant_passes_the_chart_argument():
    with patch.object(
        Analyst, "analyze", AsyncMock(return_value="done")
    ) as analyze:
        result = await CURATED_FIRST_SPEC.tool.coroutine(
            "query", chart="custom", state={"statistics": []}
        )

    assert result == "done"
    assert analyze.await_args.kwargs["chart"] == "custom"


async def test_default_tool_passes_no_chart_argument():
    with patch.object(
        Analyst, "analyze", AsyncMock(return_value="done")
    ) as analyze:
        await SPEC.tool.coroutine("query", state={"statistics": []})

    assert analyze.await_args.kwargs["chart"] is None
