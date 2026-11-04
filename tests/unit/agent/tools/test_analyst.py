"""analysis_inputs on the CodeAct path: the insight records the pulls whose
input file its code read, not every pull of the thread."""

from base64 import b64decode
from unittest.mock import AsyncMock, patch

import pytest
import structlog

from src.agent.datasets.handlers.analytics_handler import (
    LAND_GHG_INVENTORY_ID,
    TREE_COVER_LOSS_ID,
)
from src.agent.subagents.analyst import tool as analyst_tool
from src.agent.subagents.analyst.code_executors.base import (
    ChartInsight,
    CodeActPart,
    ExecutionResult,
    MultiChartInsight,
    PartType,
)
from src.agent.subagents.analyst.tool import Analyst, prepare_dataframes
from src.api.services.analysis_inputs import input_from_statistics

ROWS = {"year": [2020, 2021], "value": [1.0, 2.0]}


def _stat(stat_id, *, area="Brazil", start="2020-01-01", **overrides):
    return {
        "id": stat_id,
        "dataset_id": TREE_COVER_LOSS_ID,
        "dataset_name": "Tree cover loss",
        "start_date": start,
        "end_date": "2021-12-31",
        "source_url": f"https://analytics.example.com/result/{stat_id}",
        "aoi_names": [area],
        "aoi_ids": [area[:3].upper()],
        "aoi_sources": ["gadm"],
        "parameters": None,
        "context_layer": None,
        **overrides,
    }


def _executor(*code_blocks):
    """A code executor whose code is `code_blocks`."""

    class FakeExecutor:
        def build_file_references(self, dataframes):
            return "\n".join(
                f"- input_file_{i}.csv" for i in range(len(dataframes))
            )

        async def prepare_dataframes(self, dataframes):
            return []

        async def execute(self, prompt, file_refs):
            return ExecutionResult(
                parts=[
                    CodeActPart(type=PartType.CODE_BLOCK, content=code)
                    for code in code_blocks
                ],
                chart_data=[{"year": 2020, "value": 1.0}],
                insight=MultiChartInsight(
                    charts=[
                        ChartInsight(
                            title="Loss",
                            chart_type="bar",
                            x_axis="year",
                            y_axis="value",
                        )
                    ]
                ),
            )

    return FakeExecutor


class FakeTextGenerator:
    async def generate(self, charts, dataset, query, **kwargs):
        return type(
            "Text",
            (),
            {"primary_insight": "Loss fell.", "follow_up_suggestions": []},
        )()


@pytest.fixture
def run():
    """Run the CodeAct path with fake I/O. Statistics whose id is in
    `failing` load no data. Returns (command, persist mock)."""

    async def _run(statistics, *code_blocks, failing=()):
        async def load(stat):
            return None if stat.get("id") in failing else dict(ROWS)

        persist = AsyncMock(return_value="insight-1")
        with (
            patch.object(analyst_tool, "_load_statistics_data", load),
            patch.object(analyst_tool, "persist_insight", persist),
            patch.object(analyst_tool, "current_user_id", return_value="u"),
            patch.object(
                analyst_tool, "GeminiCodeExecutor", _executor(*code_blocks)
            ),
            patch.object(
                analyst_tool, "InsightTextGenerator", FakeTextGenerator
            ),
        ):
            command = await Analyst().analyze(
                "tree cover loss",
                statistics=statistics,
                tool_call_id="call-1",
                language="en",
            )
        return command, persist

    return _run


def _recorded(command, persist):
    """The value in the state update; the persisted value must match."""
    update = command.update
    assert update["insight_id"] == "insight-1"
    assert (
        persist.await_args.kwargs["analysis_inputs"]
        == (update["analysis_inputs"])
    )
    return update["analysis_inputs"]


async def test_one_file_read_records_its_pull(run):
    brazil = _stat("a")
    command, persist = await run(
        [brazil], 'df = pd.read_csv("input_file_0.csv")'
    )
    assert _recorded(command, persist) == [input_from_statistics(brazil)]


async def test_only_the_files_read_are_recorded_in_pull_order(run):
    brazil, peru = _stat("a"), _stat("b", area="Peru")
    chile = _stat("c", area="Chile")
    command, persist = await run(
        [brazil, peru, chile],
        'second = pd.read_csv("input_file_2.csv")',
        'first = pd.read_csv("input_file_0.csv")',
    )
    assert _recorded(command, persist) == [
        input_from_statistics(brazil),
        input_from_statistics(chile),
    ]


async def test_a_pull_that_did_not_load_shifts_the_file_index(run):
    failed = _stat("a", area="Argentina")
    brazil, peru = _stat("b"), _stat("c", area="Peru")
    command, persist = await run(
        [failed, brazil, peru],
        'df = pd.read_csv("input_file_0.csv")',
        failing={"a"},
    )
    assert _recorded(command, persist) == [input_from_statistics(brazil)]


async def test_a_curated_only_pull_takes_no_file_index(run):
    lgms = _stat("a", dataset_id=LAND_GHG_INVENTORY_ID, dataset_name="LGMS")
    brazil = _stat("b")
    command, persist = await run(
        [lgms, brazil], 'df = pd.read_csv("input_file_0.csv")'
    )
    assert _recorded(command, persist) == [input_from_statistics(brazil)]


async def test_repeated_reads_and_repeated_pulls_give_one_entry(run):
    brazil, again = _stat("a"), _stat("b")
    command, persist = await run(
        [brazil, again],
        'df = pd.read_csv("input_file_0.csv")\n'
        'df2 = pd.read_csv("input_file_0.csv")',
        'df3 = pd.read_csv("input_file_1.csv")',
    )
    assert _recorded(command, persist) == [input_from_statistics(brazil)]


async def test_an_unknown_file_index_is_ignored(run):
    brazil = _stat("a")
    with structlog.testing.capture_logs() as logs:
        command, persist = await run(
            [brazil],
            'df = pd.read_csv("input_file_0.csv")\n'
            'x = pd.read_csv("input_file_5.csv")',
        )
    assert _recorded(command, persist) == [input_from_statistics(brazil)]
    assert any(
        log["event"] == "analysis_inputs_unknown_input_file"
        and log["index"] == 5
        for log in logs
    )


async def test_code_that_reads_no_file_records_null_and_warns(run):
    with structlog.testing.capture_logs() as logs:
        command, persist = await run([_stat("a")], "print('no data')")
    assert "analysis_inputs" in command.update
    assert _recorded(command, persist) is None
    assert any(log["event"] == "analysis_inputs_not_recorded" for log in logs)
    # The insight is still saved and shown.
    assert command.update["charts_data"]


async def test_the_file_is_detected_before_the_url_swap(run):
    brazil = _stat("a")
    command, persist = await run(
        [brazil], 'df = pd.read_csv("input_file_0.csv")'
    )
    code = b64decode(command.update["codeact_parts"][0]["content"]).decode()
    assert brazil["source_url"] in code
    assert "input_file_0.csv" not in code
    assert _recorded(command, persist) == [input_from_statistics(brazil)]


async def test_prepare_dataframes_lists_the_statistics_that_loaded():
    failed, brazil = _stat("a", area="Argentina"), _stat("b")

    async def load(stat):
        return None if stat["id"] == "a" else dict(ROWS)

    with patch.object(analyst_tool, "_load_statistics_data", load):
        dataframes, source_urls, loaded = await prepare_dataframes(
            [failed, brazil]
        )

    assert loaded == [brazil]
    assert len(dataframes) == len(source_urls) == 1
