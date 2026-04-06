import pandas as pd
import pytest
from langchain_core.messages import ToolMessage

from src.agent.tools.data_handlers.analytics_handler import (
    DIST_ALERT_ID,
    GRASSLANDS_ID,
    LAND_COVER_CHANGE_ID,
    TREE_COVER_LOSS_ID,
)
from src.agent.tools.models.dataset_option import DatasetOption
from src.agent.tools.models.dataset_selection_result import (
    DatasetSelectionResult,
)
from src.agent.tools.pick_dataset import pick_dataset_func
from src.shared.config import SharedSettings

pytestmark = pytest.mark.asyncio


@pytest.fixture
def dataset_option() -> DatasetOption:
    return DatasetOption(
        dataset_id=4,
        context_layer="primary_forest",
        reason="Best match for annual tree cover loss analysis.",
        language="en",
    )


@pytest.fixture
def dataset_selection_result(
    dataset_option: DatasetOption,
) -> DatasetSelectionResult:
    return DatasetSelectionResult(
        dataset_id=dataset_option.dataset_id,
        dataset_name="Tree cover loss",
        context_layer=dataset_option.context_layer,
        reason=dataset_option.reason,
        tile_url="https://tiles.globalforestwatch.org/example/{z}/{x}/{y}.png",
        analytics_api_endpoint="/v0/land_change/tree_cover_loss/analytics",
        description="Tree cover loss description",
        prompt_instructions="Use tree cover loss terminology.",
        methodology="Dataset methodology",
        cautions="Dataset cautions",
        function_usage_notes="Dataset usage notes",
        citation="Dataset citation",
        content_date="2001-2024 annual",
        language=dataset_option.language,
        selection_hints="Best for annual tree cover loss questions.",
        code_instructions="Use bar charts for yearly loss.",
        presentation_instructions="Say tree cover loss, not deforestation.",
    )


@pytest.fixture
def candidate_datasets() -> pd.DataFrame:
    return pd.DataFrame(
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


class FakeDatasetCandidatePicker:
    def __init__(self, candidate_datasets: pd.DataFrame):
        self.candidate_datasets = candidate_datasets

    async def rag_candidate_datasets(self, query: str, k=3):
        return self.candidate_datasets


class FakeDatasetSelector:
    def __init__(self, selection_result: DatasetSelectionResult):
        self.selection_result = selection_result

    async def select_best_dataset(
        self, query: str, candidate_datasets: pd.DataFrame
    ):
        return self.selection_result


@pytest.fixture
def fake_candidate_picker(
    candidate_datasets: pd.DataFrame,
) -> FakeDatasetCandidatePicker:
    return FakeDatasetCandidatePicker(candidate_datasets)


@pytest.fixture
def fake_dataset_selector(
    dataset_selection_result: DatasetSelectionResult,
) -> FakeDatasetSelector:
    return FakeDatasetSelector(dataset_selection_result)


def _make_dataset_selection_result(
    dataset_selection_result: DatasetSelectionResult, **updates
) -> DatasetSelectionResult:
    return dataset_selection_result.model_copy(update=updates)


async def test_pick_dataset_func_adds_selected_dataset_to_command_update(
    dataset_selection_result: DatasetSelectionResult,
    fake_candidate_picker: FakeDatasetCandidatePicker,
    fake_dataset_selector: FakeDatasetSelector,
):
    result = await pick_dataset_func(
        query="Show tree cover loss in Brazil",
        start_date="2020-01-01",
        end_date="2024-12-31",
        tool_call_id="tool-call-1",
        candidate_picker=fake_candidate_picker,
        dataset_selector=fake_dataset_selector,
    )

    assert result.update["dataset"] == {
        **dataset_selection_result.model_dump(),
        "tile_url": "https://tiles.globalforestwatch.org/example/{z}/{x}/{y}.png&start_year=2020&end_year=2024",
    }


async def test_pick_dataset_func_adds_tool_message_to_command_update(
    fake_candidate_picker: FakeDatasetCandidatePicker,
    fake_dataset_selector: FakeDatasetSelector,
):
    result = await pick_dataset_func(
        query="Show tree cover loss in Brazil",
        start_date="2020-01-01",
        end_date="2024-12-31",
        tool_call_id="tool-call-1",
        candidate_picker=fake_candidate_picker,
        dataset_selector=fake_dataset_selector,
    )

    assert "messages" in result.update
    assert len(result.update["messages"]) == 1

    message = result.update["messages"][0]
    assert isinstance(message, ToolMessage)
    assert message.tool_call_id == "tool-call-1"
    assert "Selected dataset name: Tree cover loss" in message.content
    assert (
        "Reasoning for selection: Best match for annual tree cover loss analysis."
        in message.content
    )


async def test_pick_dataset_func_prefixes_relative_tile_url(
    candidate_datasets: pd.DataFrame,
    dataset_selection_result: DatasetSelectionResult,
):
    fake_candidate_picker = FakeDatasetCandidatePicker(candidate_datasets)
    fake_dataset_selector = FakeDatasetSelector(
        _make_dataset_selection_result(
            dataset_selection_result,
            tile_url="/v1/example-tiles/{z}/{x}/{y}.png",
        )
    )

    result = await pick_dataset_func(
        query="Show tree cover loss in Brazil",
        start_date="2020-01-01",
        end_date="2024-12-31",
        tool_call_id="tool-call-1",
        candidate_picker=fake_candidate_picker,
        dataset_selector=fake_dataset_selector,
    )

    assert result.update["dataset"]["tile_url"].startswith(
        SharedSettings.eoapi_base_url
    )


async def test_pick_dataset_func_appends_date_range_for_dist_alert(
    candidate_datasets: pd.DataFrame,
    dataset_selection_result: DatasetSelectionResult,
):
    fake_candidate_picker = FakeDatasetCandidatePicker(candidate_datasets)
    fake_dataset_selector = FakeDatasetSelector(
        _make_dataset_selection_result(
            dataset_selection_result,
            dataset_id=DIST_ALERT_ID,
            dataset_name="Global all ecosystem disturbance alerts (DIST-ALERT)",
            tile_url="https://tiles.example.com/dist-alert?foo=bar",
            context_layer=None,
        )
    )

    result = await pick_dataset_func(
        query="Show recent disturbance alerts",
        start_date="2024-01-02",
        end_date="2024-03-04",
        tool_call_id="tool-call-1",
        candidate_picker=fake_candidate_picker,
        dataset_selector=fake_dataset_selector,
    )

    assert (
        result.update["dataset"]["tile_url"]
        == "https://tiles.example.com/dist-alert?foo=bar&start_date=2024-01-02&end_date=2024-03-04"
    )


async def test_pick_dataset_func_formats_land_cover_year_with_end_date_year(
    candidate_datasets: pd.DataFrame,
    dataset_selection_result: DatasetSelectionResult,
):
    fake_candidate_picker = FakeDatasetCandidatePicker(candidate_datasets)
    fake_dataset_selector = FakeDatasetSelector(
        _make_dataset_selection_result(
            dataset_selection_result,
            dataset_id=LAND_COVER_CHANGE_ID,
            dataset_name="Global land cover",
            tile_url="https://tiles.example.com/land-cover/{year}/{{z}}/{{x}}/{{y}}.png",
            context_layer=None,
        )
    )

    result = await pick_dataset_func(
        query="Show land cover",
        start_date="2018-01-01",
        end_date="2020-12-31",
        tool_call_id="tool-call-1",
        candidate_picker=fake_candidate_picker,
        dataset_selector=fake_dataset_selector,
    )

    assert (
        result.update["dataset"]["tile_url"]
        == "https://tiles.example.com/land-cover/2020/{z}/{x}/{y}.png"
    )


async def test_pick_dataset_func_falls_back_to_2022_for_out_of_range_grasslands_year(
    candidate_datasets: pd.DataFrame,
    dataset_selection_result: DatasetSelectionResult,
):
    fake_candidate_picker = FakeDatasetCandidatePicker(candidate_datasets)
    fake_dataset_selector = FakeDatasetSelector(
        _make_dataset_selection_result(
            dataset_selection_result,
            dataset_id=GRASSLANDS_ID,
            dataset_name="Global natural/semi-natural grassland extent",
            tile_url="https://tiles.example.com/grasslands/{year}/{{z}}/{{x}}/{{y}}.png",
            context_layer=None,
        )
    )

    result = await pick_dataset_func(
        query="Show grasslands",
        start_date="2024-01-01",
        end_date="2025-12-31",
        tool_call_id="tool-call-1",
        candidate_picker=fake_candidate_picker,
        dataset_selector=fake_dataset_selector,
    )

    assert (
        result.update["dataset"]["tile_url"]
        == "https://tiles.example.com/grasslands/2022/{z}/{x}/{y}.png"
    )


async def test_pick_dataset_func_falls_back_to_full_range_for_out_of_range_tree_cover_loss_year(
    candidate_datasets: pd.DataFrame,
    dataset_selection_result: DatasetSelectionResult,
):
    fake_candidate_picker = FakeDatasetCandidatePicker(candidate_datasets)
    fake_dataset_selector = FakeDatasetSelector(
        _make_dataset_selection_result(
            dataset_selection_result,
            dataset_id=TREE_COVER_LOSS_ID,
        )
    )

    result = await pick_dataset_func(
        query="Show tree cover loss in Brazil",
        start_date="1999-01-01",
        end_date="2025-12-31",
        tool_call_id="tool-call-1",
        candidate_picker=fake_candidate_picker,
        dataset_selector=fake_dataset_selector,
    )

    assert (
        result.update["dataset"]["tile_url"]
        == "https://tiles.globalforestwatch.org/example/{z}/{x}/{y}.png&start_year=2001&end_year=2024"
    )


async def test_pick_dataset_func_raises_value_error_for_invalid_start_date(
    fake_candidate_picker: FakeDatasetCandidatePicker,
    fake_dataset_selector: FakeDatasetSelector,
):
    with pytest.raises(ValueError):
        await pick_dataset_func(
            query="Show tree cover loss in Brazil",
            start_date="2020/01/01",
            end_date="2024-12-31",
            tool_call_id="tool-call-1",
            candidate_picker=fake_candidate_picker,
            dataset_selector=fake_dataset_selector,
        )
