"""replay_chat streams each insight with its analysis_inputs, even when an
earlier insight in the thread had the same inputs."""

import json
from datetime import datetime
from types import SimpleNamespace

from src.api.services import chat as chat_service

INPUTS = [
    {
        "areas": [{"name": "Brazil", "source": "gadm", "src_id": "BRA"}],
        "dataset_id": 4,
        "dataset_name": "Tree cover loss",
        "start_date": "2020-01-01",
        "end_date": "2020-12-31",
        "canopy_cover": 30,
        "context_layer": None,
    }
]
DATASET = {"dataset_id": 4, "dataset_name": "Tree cover loss"}


def _checkpoint(step: int, values: dict):
    return SimpleNamespace(
        metadata={"step": step},
        values={"messages": [], **values},
        created_at=datetime(2026, 11, 4).isoformat(),
        config={
            "configurable": {
                "checkpoint_id": f"cp-{step}",
                "thread_id": "thread-1",
            }
        },
    )


async def _replay(monkeypatch, checkpoints) -> list[dict]:
    class FakeZeno:
        async def aget_state_history(self, config):
            for checkpoint in checkpoints:
                yield checkpoint

    async def fake_fetch_zeno(*args, **kwargs):
        return FakeZeno()

    monkeypatch.setattr(chat_service, "fetch_zeno", fake_fetch_zeno)
    lines = [line async for line in chat_service.replay_chat("thread-1")]
    return [json.loads(json.loads(line)["update"]) for line in lines]


async def test_an_insight_with_the_same_inputs_still_carries_them(
    monkeypatch,
):
    updates = await _replay(
        monkeypatch,
        [
            _checkpoint(
                0,
                {
                    "dataset": DATASET,
                    "insight_id": "insight-1",
                    "analysis_inputs": INPUTS,
                },
            ),
            # "Show that as a line chart": a new insight, the same pull.
            _checkpoint(
                1,
                {
                    "dataset": DATASET,
                    "insight_id": "insight-2",
                    "analysis_inputs": INPUTS,
                },
            ),
        ],
    )

    assert updates[0]["insight_id"] == "insight-1"
    assert updates[0]["analysis_inputs"] == INPUTS
    assert updates[1]["insight_id"] == "insight-2"
    assert updates[1]["analysis_inputs"] == INPUTS
    # Every other key keeps the dedupe.
    assert "dataset" in updates[0]
    assert "dataset" not in updates[1]


async def test_a_step_without_a_new_insight_does_not_repeat_the_inputs(
    monkeypatch,
):
    updates = await _replay(
        monkeypatch,
        [
            _checkpoint(
                0, {"insight_id": "insight-1", "analysis_inputs": INPUTS}
            ),
            _checkpoint(
                1,
                {
                    "insight_id": "insight-1",
                    "analysis_inputs": INPUTS,
                    "dashboard_id": "dashboard-1",
                },
            ),
        ],
    )

    assert "insight_id" not in updates[1]
    assert "analysis_inputs" not in updates[1]


async def test_a_checkpoint_saved_before_the_key_replays_null(monkeypatch):
    updates = await _replay(
        monkeypatch, [_checkpoint(0, {"insight_id": "insight-old"})]
    )

    assert updates[0]["insight_id"] == "insight-old"
    assert "analysis_inputs" in updates[0]
    assert updates[0]["analysis_inputs"] is None
