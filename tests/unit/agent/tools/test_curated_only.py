"""Guards for curated-only datasets (LGMS): standard charts only, one area,
no restyle, and no chart values sent to the agent."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.agent.datasets.config import DATASETS
from src.agent.datasets.curated_only import (
    CURATED_ONLY_DATA_WITHHELD,
    CURATED_ONLY_DATASET_IDS,
    CURATED_ONLY_SESSION_NOTE,
    CURATED_ONLY_TOOL_INSTRUCTION,
    is_curated_only,
)
from src.agent.datasets.handlers.analytics_handler import (
    LAND_GHG_INVENTORY_ID,
    TREE_COVER_LOSS_ID,
)
from src.agent.middleware import format_session_block
from src.agent.subagents.analyst import tool as analyst_tool
from src.agent.subagents.analyst.charts.model import InsightChart
from src.agent.subagents.analyst.tool import Analyst
from src.agent.tools.inspect_view_context import format_chart_data
from src.agent.tools.pull_data import pull_data
from src.agent.tools.update_insight_display import update_insight_display
from tests.unit.api.services.test_chart_generators import LGMS_DATA

LGMS_NAME = "Land GHG Monitoring System (LGMS)"
BRAZIL = {
    "name": "Brazil",
    "subtype": "country",
    "source": "gadm",
    "src_id": "BRA",
}
PERU = {
    "name": "Peru",
    "subtype": "country",
    "source": "gadm",
    "src_id": "PER",
}


def _content(command):
    return command.update["messages"][0].content


def _lgms_statistics(aoi_names=("Pará",)):
    return {
        "id": str(uuid4()),
        "dataset_id": LAND_GHG_INVENTORY_ID,
        "dataset_name": LGMS_NAME,
        "start_date": "2016-01-01",
        "end_date": "2024-12-31",
        "source_url": "https://analytics.example.com/result/lgms",
        "aoi_names": list(aoi_names),
        "aoi_ids": [f"id-{i}" for i, _ in enumerate(aoi_names)],
    }


# --- catalog flag -----------------------------------------------------------


def test_only_lgms_is_curated_only():
    assert CURATED_ONLY_DATASET_IDS == {LAND_GHG_INVENTORY_ID}
    assert is_curated_only(LAND_GHG_INVENTORY_ID)
    assert not is_curated_only(TREE_COVER_LOSS_ID)
    assert not is_curated_only(None)


def test_catalog_flag_drives_the_set():
    flagged = {ds["dataset_id"] for ds in DATASETS if ds.get("curated_only")}
    assert flagged == CURATED_ONLY_DATASET_IDS


# --- generate_insights ------------------------------------------------------


@pytest.fixture
def curated_run():
    """Patch I/O around the curated-only path; the executor and the text
    generator fail the test if they are reached."""
    persist = AsyncMock(return_value="insight-1")
    with (
        patch.object(
            analyst_tool,
            "_load_statistics_data",
            AsyncMock(return_value={k: list(v) for k, v in LGMS_DATA.items()}),
        ),
        patch.object(analyst_tool, "persist_insight", persist),
        patch.object(analyst_tool, "current_user_id", return_value="user-1"),
        patch.object(
            analyst_tool,
            "GeminiCodeExecutor",
            side_effect=AssertionError("code executor must not run"),
        ),
        patch.object(
            analyst_tool,
            "InsightTextGenerator",
            side_effect=AssertionError("text generator must not run"),
        ),
    ):
        yield persist


async def test_curated_only_insight_skips_every_model(curated_run):
    command = await Analyst().analyze(
        "which year had the highest soil emissions?",
        statistics=[_lgms_statistics()],
        tool_call_id="call-1",
        language="en",
    )

    update = command.update
    assert update["insight_id"] == "insight-1"
    assert len(update["charts_data"]) == 4
    assert update["follow_up_suggestions"] == []
    assert update["codeact_parts"] == []
    assert update["insight"] == (
        f"Standard {LGMS_NAME} charts for Pará, 2016."
    )

    insight = curated_run.await_args.args[0]
    assert all(c.dataset_id == LAND_GHG_INVENTORY_ID for c in insight.charts)
    assert curated_run.await_args.kwargs["codeact_parts"] == []


async def test_curated_only_tool_message_carries_no_values(curated_run):
    command = await Analyst().analyze(
        "show me the data",
        statistics=[_lgms_statistics()],
        tool_call_id="call-1",
        language="en",
    )

    content = _content(command)
    assert CURATED_ONLY_TOOL_INSTRUCTION in content
    for value in ("33.0", "-2.0", "10.0", "200.0"):
        assert value not in content


async def test_curated_only_uses_the_latest_pull_only(curated_run):
    """An earlier pull of another dataset does not turn the insight into a
    code-executor run."""
    tcl = {"dataset_id": TREE_COVER_LOSS_ID, "dataset_name": "Tree cover loss"}

    command = await Analyst().analyze(
        "lgms",
        statistics=[tcl, _lgms_statistics()],
        tool_call_id="call-1",
        language="en",
    )

    assert len(command.update["charts_data"]) == 4


async def test_curated_only_refuses_more_than_one_area(curated_run):
    command = await Analyst().analyze(
        "compare",
        statistics=[_lgms_statistics(aoi_names=("Pará", "Amazonas"))],
        tool_call_id="call-1",
        language="en",
    )

    message = command.update["messages"][0]
    assert message.status == "error"
    assert "one area" in message.content
    curated_run.assert_not_awaited()


async def test_curated_only_without_data_does_not_fall_back(curated_run):
    with patch.object(
        analyst_tool, "_load_statistics_data", AsyncMock(return_value=None)
    ):
        command = await Analyst().analyze(
            "lgms",
            statistics=[_lgms_statistics()],
            tool_call_id="call-1",
            language="en",
        )

    assert command.update["messages"][0].status == "error"
    curated_run.assert_not_awaited()


async def test_code_executor_never_receives_a_curated_only_pull():
    tcl = {"dataset_id": TREE_COVER_LOSS_ID, "dataset_name": "Tree cover loss"}
    resolve = AsyncMock(return_value=(None, [], "", "stop here"))

    with patch.object(Analyst, "_resolve_charts", resolve):
        await Analyst().analyze(
            "tree cover loss",
            statistics=[_lgms_statistics(), tcl],
            tool_call_id="call-1",
        )

    assert resolve.await_args.args[1] == [tcl]


# --- data sent to the agent -------------------------------------------------


def _chart(dataset_id):
    return InsightChart(
        position=0,
        title="Net GHG Flux Summary",
        chart_type="bar",
        x_axis="year",
        y_axis="value",
        chart_data=[{"year": 2020, "value": 123.5}],
        dataset_id=dataset_id,
    )


async def test_format_chart_data_withholds_curated_only_rows():
    text = await format_chart_data(_chart(LAND_GHG_INVENTORY_ID))

    assert CURATED_ONLY_DATA_WITHHELD in text
    assert "123.5" not in text


async def test_format_chart_data_keeps_other_rows():
    assert "123.5" in await format_chart_data(_chart(TREE_COVER_LOSS_ID))


def test_session_block_marks_curated_only_dataset():
    block = format_session_block(
        {
            "dataset": {
                "dataset_id": LAND_GHG_INVENTORY_ID,
                "dataset_name": LGMS_NAME,
            }
        }
    )
    assert CURATED_ONLY_SESSION_NOTE in block


def test_session_block_leaves_other_datasets_alone():
    block = format_session_block(
        {"dataset": {"dataset_id": TREE_COVER_LOSS_ID, "dataset_name": "TCL"}}
    )
    assert CURATED_ONLY_SESSION_NOTE not in block


# --- update_insight_display --------------------------------------------------


async def test_update_insight_display_refuses_curated_only_insight():
    row = SimpleNamespace(
        charts=[SimpleNamespace(dataset_id=LAND_GHG_INVENTORY_ID)]
    )
    with (
        patch(
            "src.agent.tools.update_insight_display._load_editable_insight",
            AsyncMock(return_value=row),
        ),
        patch(
            "src.agent.tools.update_insight_display.InsightDisplayReviser",
            side_effect=AssertionError("reviser must not run"),
        ),
    ):
        command = await update_insight_display.coroutine(
            instruction="make it a pie chart",
            insight_id=str(uuid4()),
            state={},
            tool_call_id="call-1",
        )

    message = command.update["messages"][0]
    assert message.status == "error"
    assert "Nothing was updated" in message.content


# --- pull_data ---------------------------------------------------------------


async def test_pull_data_refuses_two_areas_for_curated_only_dataset():
    class Orchestrator:
        async def pull_data(self, **kwargs):
            raise AssertionError("handler must not run")

    with patch(
        "src.agent.tools.pull_data.data_pull_orchestrator", Orchestrator()
    ):
        command = await pull_data.coroutine(
            query="compare Brazil and Peru",
            state={
                "dataset": {
                    "dataset_id": LAND_GHG_INVENTORY_ID,
                    "dataset_name": LGMS_NAME,
                },
                "aoi_selection": {
                    "name": "Brazil, Peru",
                    "aois": [BRAZIL, PERU],
                },
            },
            tool_call_id="call-1",
        )

    content = _content(command)
    assert LGMS_NAME in content
    assert "one area" in content
    assert "statistics" not in command.update
