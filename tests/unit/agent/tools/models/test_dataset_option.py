import pytest
from pydantic import ValidationError

from src.agent.tools.data_handlers.analytics_handler import (
    TREE_COVER_LOSS_BY_DRIVER_ID,
)
from src.agent.tools.models.dataset_option import DatasetOption


def test_dataset_option_accepts_valid_dataset_id():
    option = DatasetOption(
        dataset_id=4,
        context_layer=None,
        reason="Best match for annual tree cover loss analysis.",
        language="en",
    )

    assert option.dataset_id == 4


def test_dataset_option_rejects_invalid_dataset_id():
    with pytest.raises(ValidationError, match="Invalid dataset ID: 999"):
        DatasetOption(
            dataset_id=999,
            context_layer=None,
            reason="Invalid dataset",
            language="en",
        )


def test_dataset_option_preserves_valid_context_layer():
    option = DatasetOption(
        dataset_id=8,
        context_layer="driver",
        reason="Best match for annual tree cover loss analysis.",
        language="en",
    )

    assert option.context_layer == "driver"


def test_dataset_option_clears_invalid_context_layer():
    option = DatasetOption(
        dataset_id=4,
        context_layer="make_believe",
        reason="Best match for annual tree cover loss analysis.",
        language="en",
    )

    assert option.context_layer is None


def test_dataset_option_forces_driver_context_for_tree_cover_loss_by_driver():
    option = DatasetOption(
        dataset_id=TREE_COVER_LOSS_BY_DRIVER_ID,
        context_layer=None,
        reason="Best match for dominant driver attribution.",
        language="en",
    )

    assert option.context_layer == "driver"
