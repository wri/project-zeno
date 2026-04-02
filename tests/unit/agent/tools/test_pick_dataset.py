from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest
from langchain_core.messages import ToolMessage

from src.agent.tools.pick_dataset import DatasetSelectionResult, pick_dataset


pytestmark = pytest.mark.asyncio


async def test_pick_dataset_returns_command_with_selected_dataset():
    candidate_datasets = pd.DataFrame(
        [
            {
                "dataset_id": 4,
                "dataset_name": "Tree cover loss",
                "tile_url": "https://tiles.globalforestwatch.org/example/{z}/{x}/{y}.png",
                "analytics_api_endpoint": "/v0/land_change/tree_cover_loss/analytics",
                "description": "Tree cover loss description",
                "prompt_instructions": "Use tree cover loss terminology.",
                "methodology": "Dataset methodology",
                "cautions": "Dataset cautions",
                "function_usage_notes": "Dataset usage notes",
                "citation": "Dataset citation",
                "content_date": "2001-2024 annual",
                "selection_hints": "Best for annual tree cover loss questions.",
                "code_instructions": "Use bar charts for yearly loss.",
                "presentation_instructions": "Say tree cover loss, not deforestation.",
            }
        ]
    )
    selection_result = DatasetSelectionResult(
        dataset_id=4,
        dataset_name="Tree cover loss",
        context_layer="primary_forest",
        reason="Best match for annual tree cover loss analysis.",
        tile_url="https://tiles.globalforestwatch.org/example/{z}/{x}/{y}.png",
        analytics_api_endpoint="/v0/land_change/tree_cover_loss/analytics",
        description="Tree cover loss description",
        prompt_instructions="Use tree cover loss terminology.",
        methodology="Dataset methodology",
        cautions="Dataset cautions",
        function_usage_notes="Dataset usage notes",
        citation="Dataset citation",
        content_date="2001-2024 annual",
        language="en",
        selection_hints="Best for annual tree cover loss questions.",
        code_instructions="Use bar charts for yearly loss.",
        presentation_instructions="Say tree cover loss, not deforestation.",
    )

    with (
        patch(
            "src.agent.tools.pick_dataset.rag_candidate_datasets",
            AsyncMock(return_value=candidate_datasets),
        ) as mock_rag,
        patch(
            "src.agent.tools.pick_dataset.select_best_dataset",
            AsyncMock(return_value=selection_result),
        ) as mock_select,
    ):
        result = await pick_dataset.coroutine(
            query="Show tree cover loss in Brazil",
            start_date="2020-01-01",
            end_date="2024-12-31",
            tool_call_id="tool-call-1",
        )

    mock_rag.assert_awaited_once_with(
        "Show tree cover loss in Brazil", k=3
    )
    mock_select.assert_awaited_once_with(
        "Show tree cover loss in Brazil", candidate_datasets
    )

    dataset = result.update["dataset"]
    assert dataset["dataset_id"] == 4
    assert dataset["dataset_name"] == "Tree cover loss"
    assert dataset["context_layer"] == "primary_forest"
    assert (
        dataset["tile_url"]
        == "https://tiles.globalforestwatch.org/example/{z}/{x}/{y}.png&start_year=2020&end_year=2024"
    )

    message = result.update["messages"][0]
    assert isinstance(message, ToolMessage)
    assert message.tool_call_id == "tool-call-1"
    assert "Selected dataset name: Tree cover loss" in message.content
    assert "Selected context layer: primary_forest" in message.content
