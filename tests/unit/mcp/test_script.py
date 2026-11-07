"""The request a pull records, and pull.py, the script that replays it.

The script runs for real, in its own Python, against a stub analytics API.
"""

import csv
import json
import subprocess
import sys

import pytest
from fastmcp import Client

import src.mcp.data as data
from src.agent.datasets.handlers import analytics_handler
from src.agent.datasets.handlers.analytics_handler import AnalyticsHandler
from src.agent.datasets.handlers.base import DataPullResult
from src.api.services.charts.base import column_to_rows
from src.mcp.charts import find_generator, generator_info
from src.mcp.script import CLI_TEMPLATE, cli_template, rows_digest
from src.mcp.server import mcp_server
from src.shared.version import get_version
from tests.unit.mcp.analytics_stub import BODY, METADATA, PARA, RESULT


async def _pull(tool: str = "pull_data"):
    async with Client(mcp_server) as client:
        return await client.call_tool(
            tool,
            {
                "aoi_ids": ["gadm:BRA.14_1"],
                "dataset_id": 4,
                "start_date": "2020-01-01",
                "end_date": "2021-12-31",
            },
        )


def _run(script: str, tmp_path, *args):
    path = tmp_path / "pull.py"
    path.write_text(script, encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-I", str(path), *args],
        capture_output=True,
        text=True,
        timeout=30,
        env={},
    )


@pytest.mark.parametrize("tool", ["pull_data", "curated_charts"])
async def test_a_pull_returns_its_request_and_a_script(replayable_pull, tool):
    result = await _pull(tool)
    structured = result.structured_content
    assert structured["request"]["body"] == BODY
    assert structured["request"]["headers"] == {"X-environment": "production"}
    assert structured["retrieved_at"].endswith("+00:00")
    assert structured["analytics_metadata"]["aoi"]["version"] == "4.1"
    assert structured["rows_sha256"] == rows_digest(
        [
            {**row, "name": "Pará"}
            for row in column_to_rows(RESULT)[::-1]  # sorted by year
        ]
    )
    assert structured["server"] == {
        "version": get_version(),
        "commit": None,
    }
    assert structured["script"].startswith('"""Tree cover loss for Pará')
    assert "standalone pull.py" in result.content[0].text
    # The script is in the structured result only, not in the model's text.
    assert "def fetch" not in result.content[0].text


async def test_the_script_writes_the_rows_the_server_returned(
    replayable_pull, api, tmp_path
):
    result = await _pull()
    structured = result.structured_content
    folder = tmp_path / "out"

    run = _run(structured["script"], tmp_path, str(folder))

    assert run.returncode == 0, run.stderr
    assert run.stderr == ""
    # It sent the recorded request.
    post = api.requests[0]
    assert post["path"] == "/v0/land_change/tree_cover_loss/analytics"
    assert post["body"] == BODY
    assert post["headers"]["x-environment"] == "production"
    assert "authorization" not in post["headers"]
    # Its rows are the server's rows: named, sorted, every column.
    with open(folder / "rows.csv", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    assert rows == [
        {key: str(value) for key, value in row.items()}
        for row in structured["rows"]
    ]
    assert [row["tree_cover_loss_year"] for row in rows] == ["2020", "2021"]
    assert rows[0]["name"] == "Pará"

    provenance = json.loads((folder / "provenance.json").read_text())
    assert provenance["result_id"] == "df747c81"
    assert provenance["replayed_result_id"] == "df747c81"
    assert provenance["areas"] == structured["areas"]
    assert "request" not in provenance
    request = json.loads((folder / "request.json").read_text())
    assert request == structured["request"]
    assert (folder / "pull.py").read_text() == structured["script"]


async def test_the_script_warns_when_the_rows_changed(
    replayable_pull, api, tmp_path
):
    result = await _pull()
    # A data release: the same request, under the same id, new numbers.
    api.result = {**RESULT, "area_ha": [693512.76, 805620.13]}

    run = _run(
        result.structured_content["script"], tmp_path, str(tmp_path / "out")
    )

    assert run.returncode == 0, run.stderr
    assert (
        "the rows differ from the ones the MCP server returned" in run.stderr
    )
    assert "filed the request" not in run.stderr
    provenance = json.loads((tmp_path / "out" / "provenance.json").read_text())
    assert provenance["replayed_rows_sha256"] != provenance["rows_sha256"]


async def test_the_script_warns_when_the_result_id_changed(
    replayable_pull, api, tmp_path
):
    result = await _pull()
    api.result_id = "0a1b2c3d"

    run = _run(
        result.structured_content["script"], tmp_path, str(tmp_path / "out")
    )

    assert run.returncode == 0, run.stderr
    assert "filed the request as 0a1b2c3d, not df747c81" in run.stderr
    assert "rows differ" not in run.stderr


def test_a_generator_links_to_the_commit_the_server_runs(monkeypatch):
    generator = find_generator(4)
    monkeypatch.setenv("GIT_SHA", "5EB91F59")
    assert generator_info(generator)["code_url"] == (
        "https://github.com/wri/project-zeno/blob/5eb91f59/"
        "src/api/services/charts/tcl.py"
    )
    # Not a commit: the link falls back to main.
    monkeypatch.setenv("GIT_SHA", "main; rm -rf")
    assert "/blob/main/" in generator_info(generator)["code_url"]


async def test_no_script_without_a_recorded_request(
    monkeypatch, replayable_pull
):
    async def fake_pull(self, **kwargs):
        return DataPullResult(
            success=True, data=dict(RESULT), message="ok", data_points_count=2
        )

    monkeypatch.setattr(data.AnalyticsHandler, "pull_data", fake_pull)
    result = await _pull()
    assert result.structured_content["script"] is None
    assert "standalone pull.py" not in result.content[0].text


async def test_the_handler_records_the_request_without_the_token(
    monkeypatch, api
):
    monkeypatch.setenv("WRI_BEARER_TOKEN", "secret")
    handler = AnalyticsHandler()
    handler.BASE_URL = api.url
    result = await handler.pull_data(
        query="",
        dataset={"dataset_id": 4, "dataset_name": "Tree cover loss"},
        start_date="2020-01-01",
        end_date="2021-12-31",
        change_over_time_query=False,
        aois=[dict(PARA)],
    )

    assert result.success, result.message
    sent = api.requests[0]
    assert sent["headers"]["authorization"] == "Bearer secret"
    assert result.analytics_api_request == {
        "method": "POST",
        "url": f"{api.url}/v0/land_change/tree_cover_loss/analytics",
        "headers": {
            "X-environment": analytics_handler.analytics_api_headers()[
                "X-environment"
            ]
        },
        "body": sent["body"],
    }
    assert result.analytics_api_metadata == METADATA


async def test_a_replay_keeps_the_rows_it_was_built_on(
    replayable_pull, api, tmp_path
):
    result = await _pull()
    script = result.structured_content["script"]
    folder = tmp_path / "out"
    _run(script, tmp_path, str(folder))
    original = (folder / "rows.csv").read_text()

    api.result = {**RESULT, "area_ha": [693512.76, 805620.13]}
    run = _run(script, tmp_path, str(folder))

    assert run.returncode == 0, run.stderr
    assert "rows.changed.csv" in run.stderr
    assert (folder / "rows.csv").read_text() == original
    assert (folder / "rows.changed.csv").read_text() != original
    provenance = json.loads((folder / "provenance.json").read_text())
    assert provenance["replayed_rows_sha256"] == provenance["rows_sha256"]
    changed = json.loads((folder / "provenance.changed.json").read_text())
    assert changed["replayed_rows_sha256"] != changed["rows_sha256"]


async def test_the_script_polls_again_after_a_failed_poll(
    replayable_pull, api, tmp_path
):
    result = await _pull()
    api.failed_polls = 2

    run = _run(
        result.structured_content["script"], tmp_path, str(tmp_path / "out")
    )

    assert run.returncode == 0, run.stderr
    assert run.stderr == ""
    assert [r["method"] for r in api.requests[-3:]] == ["GET"] * 3


async def test_a_curated_only_pull_has_no_request_or_script(
    monkeypatch, replayable_pull
):
    monkeypatch.setattr(data, "is_curated_only", lambda dataset_id: True)
    result = await _pull()
    structured = result.structured_content
    assert structured["script"] is None
    assert structured["request"] is None
    assert structured["rows"] == []


def test_the_cli_ships_the_current_template():
    assert CLI_TEMPLATE.read_text(encoding="utf-8") == cli_template(), (
        "Rebuild it: uv run python -m src.mcp.script"
    )


async def test_metadata_of_another_shape_does_not_fail_the_pull(api):
    api.metadata = ["not", "an", "object"]
    handler = AnalyticsHandler()
    handler.BASE_URL = api.url
    result = await handler.pull_data(
        query="",
        dataset={"dataset_id": 4, "dataset_name": "Tree cover loss"},
        start_date="2020-01-01",
        end_date="2021-12-31",
        change_over_time_query=False,
        aois=[dict(PARA)],
    )
    assert result.success, result.message
    assert result.analytics_api_metadata is None
