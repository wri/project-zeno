"""pick_dataset reports the date range it applied.

The tile URL is scoped to that range for date-driven layers (see
test_tile_services), so a range the model did not intend silently changes
what the map shows. These cover the note that makes it visible.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.agent.datasets.config import DATASETS
from src.agent.datasets.handlers.analytics_handler import INTEGRATED_ALERTS_ID
from src.agent.subagents.pick_dataset import (
    DatasetSelectionResult,
    pick_dataset,
)
from src.agent.subagents.pick_dataset.schema import DatasetSelectionResponse
from src.agent.subagents.pick_dataset.tool import _applied_date_range_note


def test_no_dates_requested_explains_the_default():
    note = _applied_date_range_note(
        None, None, "2023-12-01", "2026-09-08", False
    )

    assert "No date range was requested" in note
    assert "call pick_dataset again" in note


def test_missing_start_names_that_bound():
    note = _applied_date_range_note(
        None, "2026-09-08", "2023-12-01", "2026-09-08", False
    )

    assert "No start date was requested" in note
    assert "No end date" not in note


def test_missing_end_names_that_bound():
    note = _applied_date_range_note(
        "2026-08-25", None, "2026-08-25", "2026-09-08", False
    )

    assert "No end date was requested" in note


def test_clamped_range_quotes_what_was_requested():
    note = _applied_date_range_note(
        "2019-01-01", "2026-09-08", "2023-12-01", "2026-09-08", True
    )

    assert "2019-01-01 to 2026-09-08" in note
    assert "adjusted" in note


def test_honoured_range_needs_no_note():
    """A range applied exactly as asked is already on the range line."""
    note = _applied_date_range_note(
        "2026-08-25", "2026-09-08", "2026-08-25", "2026-09-08", False
    )

    assert note == ""


async def _resolve_integrated_alerts(start_date, end_date):
    """Run pick_dataset for Integrated alerts with the selector mocked out."""
    import pandas as pd

    ds = next(d for d in DATASETS if d["dataset_id"] == INTEGRATED_ALERTS_ID)
    selected = DatasetSelectionResult(
        dataset_id=ds["dataset_id"],
        dataset_name=ds["dataset_name"],
        context_layer=None,
        reason="test",
        tile_url=ds["tile_url"],
        analytics_api_endpoint=ds.get("analytics_api_endpoint", ""),
        description=ds.get("description", ""),
        prompt_instructions=ds.get("prompt_instructions", ""),
        methodology=ds.get("methodology", ""),
        cautions=ds.get("cautions", ""),
        function_usage_notes=ds.get("function_usage_notes", ""),
        citation=ds.get("citation", ""),
        content_date=ds.get("content_date", ""),
    )
    tool_call_id = str(uuid.uuid4())

    with (
        patch(
            "src.agent.subagents.pick_dataset.tool.rag_candidate_datasets",
            new_callable=AsyncMock,
            return_value=pd.DataFrame([ds]),
        ),
        patch(
            "src.agent.subagents.pick_dataset.tool.select_best_dataset",
            new_callable=AsyncMock,
            return_value=DatasetSelectionResponse(
                selected_dataset=selected, reason="test"
            ),
        ),
    ):
        return await pick_dataset.ainvoke(
            {
                "type": "tool_call",
                "name": "pick_dataset",
                "id": tool_call_id,
                "args": {
                    "query": "alerts",
                    "start_date": start_date,
                    "end_date": end_date,
                    # Set so resolve_language() is not consulted.
                    "state": {"language": "en"},
                    "tool_call_id": tool_call_id,
                },
            }
        )


@pytest.mark.asyncio
async def test_tool_message_reports_the_range_the_tile_url_uses():
    command = await _resolve_integrated_alerts("2026-08-25", "2026-09-08")

    message = command.update["messages"][0].content
    assert "## Applied date range" in message
    assert "2026-08-25 to 2026-09-08" in message

    tile_url = command.update["dataset"]["tile_url"]
    assert "start_date=2026-08-25" in tile_url
    assert "end_date=2026-09-08" in tile_url


@pytest.mark.asyncio
async def test_omitted_dates_are_called_out_in_the_tool_message():
    """The bug this guards: no dates in, full coverage on the map, silently."""
    command = await _resolve_integrated_alerts(None, None)

    message = command.update["messages"][0].content
    assert "No date range was requested" in message

    dataset = command.update["dataset"]
    assert dataset["start_date"] == "2023-12-01"
    assert f"start_date={dataset['start_date']}" in dataset["tile_url"]
