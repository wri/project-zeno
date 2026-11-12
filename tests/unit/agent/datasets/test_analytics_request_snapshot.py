"""The exact request the analytics handler sends, for every catalog dataset.

A wrong payload does not fail: the analytics API answers a well-formed
request that means something else, with data that looks right. So every
request is pinned here, endpoint and JSON, for each dataset, each of its
context layers, its canopy cover parameter and each area type. The agent's
pull_data, the MCP server's pull_data and /api/analyze all send these.

A deliberate payload change shows up as a readable diff of the snapshot.
Regenerate it with:

    UPDATE_ANALYTICS_SNAPSHOT=1 uv run pytest \\
        tests/unit/agent/datasets/test_analytics_request_snapshot.py
"""

import json
import os
from pathlib import Path

import pytest

from src.agent.datasets.config import DATASETS
from src.agent.datasets.handlers import analytics_handler
from src.agent.datasets.handlers.analytics_handler import (
    LAND_COVER_CHANGE_ID,
    AnalyticsHandler,
)

SNAPSHOT = Path(__file__).parent / "fixtures" / "analytics_requests.json"

AREAS = {
    "country": {
        "source": "gadm",
        "src_id": "BRA",
        "name": "Brazil",
        "subtype": "country",
    },
    "state": {
        "source": "gadm",
        "src_id": "BRA.14_1",
        "name": "Pará, Brazil",
        "subtype": "state-province",
    },
    "kba": {
        "source": "kba",
        "src_id": "19363",
        "name": "Yasuní",
        "subtype": "key-biodiversity-area",
    },
    "wdpa": {
        "source": "wdpa",
        "src_id": "555622",
        "name": "Yasuní National Park",
        "subtype": "protected-area",
    },
    "landmark": {
        "source": "landmark",
        "src_id": "1234",
        "name": "Waorani",
        "subtype": "indigenous-and-community-land",
    },
}


def _cases() -> list[tuple[str, dict, list[str], bool]]:
    """(case id, dataset fields, area keys, change over time)."""
    cases = []
    for ds in DATASETS:
        ds_id = ds["dataset_id"]
        base = {"dataset_id": ds_id, "dataset_name": ds["dataset_name"]}
        cases.append((f"{ds_id}/country", base, ["country"], False))
        cases.append((f"{ds_id}/two-states", base, ["state", "state"], False))
        for layer in ds.get("context_layers") or []:
            cases.append(
                (
                    f"{ds_id}/context_layer={layer['value']}",
                    {**base, "context_layer": layer["value"]},
                    ["country"],
                    False,
                )
            )
        for param in ds.get("parameters") or []:
            if param["name"] == "canopy_cover":
                value = param["values"][-1]
                cases.append(
                    (
                        f"{ds_id}/canopy_cover={value}",
                        {
                            **base,
                            "parameters": [
                                {"name": "canopy_cover", "values": [value]}
                            ],
                        },
                        ["country"],
                        False,
                    )
                )
        if ds_id == LAND_COVER_CHANGE_ID:
            cases.append(
                (f"{ds_id}/change_over_time", base, ["country"], True)
            )
    for kind in ("kba", "wdpa", "landmark"):
        tcl = {"dataset_id": 4, "dataset_name": "Tree cover loss"}
        cases.append((f"4/{kind}", tcl, [kind], False))
    return cases


class _RecordingClient:
    """Stands in for httpx.AsyncClient: records the POST, answers failed."""

    requests: list[dict] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None):
        _RecordingClient.requests.append({"url": url, "json": json})

        class Response:
            status_code = 500
            text = "recorded"
            headers: dict = {}

            def json(self):
                return {"status": "failed", "data": {}}

        return Response()


async def _record(dataset, areas, change_over_time) -> dict:
    _RecordingClient.requests = []
    handler = AnalyticsHandler()
    handler.BASE_URL = "https://analytics.test"
    await handler.pull_data(
        query="",
        dataset=dataset,
        start_date="2015-01-01",
        end_date="2020-12-31",
        change_over_time_query=change_over_time,
        aois=[dict(AREAS[key]) for key in areas],
    )
    if not _RecordingClient.requests:
        return {"refused_before_the_api": True}
    request = _RecordingClient.requests[0]
    return {
        "url": request["url"].removeprefix("https://analytics.test"),
        "json": request["json"],
    }


async def test_every_request_matches_the_snapshot(monkeypatch):
    monkeypatch.setattr(
        analytics_handler.httpx, "AsyncClient", _RecordingClient
    )
    recorded = {}
    for case_id, dataset, areas, change_over_time in _cases():
        recorded[case_id] = await _record(dataset, areas, change_over_time)

    if os.getenv("UPDATE_ANALYTICS_SNAPSHOT"):
        SNAPSHOT.parent.mkdir(exist_ok=True)
        SNAPSHOT.write_text(
            json.dumps(recorded, indent=2, sort_keys=True, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
        pytest.skip("snapshot written")

    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert sorted(recorded) == sorted(expected), "cases added or removed"
    for case_id in expected:
        assert recorded[case_id] == expected[case_id], case_id
