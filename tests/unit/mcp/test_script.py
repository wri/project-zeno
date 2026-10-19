"""The request a pull records, and pull.py, the script that replays it.

The script runs for real, in its own Python, against a stub analytics API.
"""

import csv
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastmcp import Client

import src.mcp.data as data
from src.agent.datasets.handlers import analytics_handler
from src.agent.datasets.handlers.analytics_handler import AnalyticsHandler
from src.agent.datasets.handlers.base import DataPullResult
from src.mcp.server import mcp_server

PARA = {
    "source": "gadm",
    "src_id": "BRA.14_1",
    "name": "Pará, Brazil",
    "subtype": "state-province",
    "bbox": [-58.9, -9.8, -46.0, 2.6],
}
# Column-oriented, in no particular order, as the analytics API returns it.
RESULT = {
    "aoi_id": ["BRA.14", "BRA.14"],
    "aoi_type": ["admin", "admin"],
    "tree_cover_loss_year": [2021, 2020],
    "area_ha": [693512.76, 805620.12],
}
BODY = {
    "aoi": {"type": "admin", "ids": ["BRA.14"]},
    "start_year": "2020",
    "end_year": "2021",
    "canopy_cover": 30,
}


class StubApi:
    """The analytics API: a POST answers pending with a link, a GET of the
    link answers the result. Records each request."""

    def __init__(self, result_id: str = "df747c81"):
        self.result_id = result_id
        self.requests: list[dict] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self, payload):
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Retry-After", "0")
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                length = int(self.headers["Content-Length"])
                stub.requests.append(
                    {
                        "method": "POST",
                        "path": self.path,
                        "headers": {
                            key.lower(): value
                            for key, value in self.headers.items()
                        },
                        "body": json.loads(self.rfile.read(length)),
                    }
                )
                self._answer(
                    {
                        "status": "pending",
                        "data": {
                            "link": f"{stub.url}/result/{stub.result_id}"
                        },
                    }
                )

            def do_GET(self):
                stub.requests.append({"method": "GET", "path": self.path})
                self._answer(
                    {
                        "status": "success",
                        "data": {"status": "saved", "result": RESULT},
                    }
                )

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


@pytest.fixture
def api():
    stub = StubApi()
    yield stub
    stub.close()


@pytest.fixture
def pulled(monkeypatch, api):
    """pull_data's area lookup and analytics handler, stubbed: the handler
    answers as the real one does, with the request it sent."""

    async def fake_lookup(aoi_ids):
        return [dict(PARA)]

    async def fake_pull(self, **kwargs):
        rows = {**RESULT, "name": ["Pará", "Pará"]}
        return DataPullResult(
            success=True,
            data=rows,
            message="ok",
            data_points_count=2,
            analytics_api_url=f"{api.url}/result/df747c81",
            analytics_api_request={
                "method": "POST",
                "url": f"{api.url}/v0/land_change/tree_cover_loss/analytics",
                "headers": {"X-environment": "production"},
                "body": BODY,
            },
        )

    monkeypatch.setattr(data, "lookup_areas", fake_lookup)
    monkeypatch.setattr(data.AnalyticsHandler, "pull_data", fake_pull)


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
async def test_a_pull_returns_its_request_and_a_script(pulled, tool):
    result = await _pull(tool)
    structured = result.structured_content
    assert structured["request"]["body"] == BODY
    assert structured["request"]["headers"] == {"X-environment": "production"}
    assert structured["retrieved_at"].endswith("+00:00")
    assert structured["script"].startswith('"""Tree cover loss for Pará')
    assert "standalone pull.py" in result.content[0].text
    # The script is in the structured result only, not in the model's text.
    assert "def fetch" not in result.content[0].text


async def test_the_script_writes_the_rows_the_server_returned(
    pulled, api, tmp_path
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


async def test_the_script_warns_when_the_result_changed(pulled, api, tmp_path):
    result = await _pull()
    api.result_id = "0a1b2c3d"

    run = _run(
        result.structured_content["script"], tmp_path, str(tmp_path / "out")
    )

    assert run.returncode == 0, run.stderr
    assert "answered with result 0a1b2c3d, not df747c81" in run.stderr


async def test_no_script_without_a_recorded_request(monkeypatch, pulled):
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
