from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from src.agent.tools.data_handlers.analytics_handler import (
    TREE_COVER_LOSS_BY_DRIVER_ID,
)
from src.agent.tools.datasets_config import DATASETS
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class DatasetOption(BaseModel):
    dataset_id: int = Field(
        description="ID of the dataset that best matches the user query."
    )
    context_layer: Optional[str] = Field(
        None,
        description="Pick a single context layer from the dataset if relevant.",
    )
    reason: str = Field(
        description="Short reason why the dataset is the best match."
    )
    language: str = Field(
        description="Language of the user query.",
    )

    @field_validator("dataset_id")
    def validate_dataset_id(cls, v):
        if v not in [ds["dataset_id"] for ds in DATASETS]:
            raise ValueError(f"Invalid dataset ID: {v}")
        return v

    @model_validator(mode="after")
    def validate_context_layer_for_dataset(self) -> "DatasetOption":
        """Ensure context_layer is valid for the chosen dataset_id (runs after all fields)."""
        dataset_id = self.dataset_id
        if dataset_id is None:
            self.context_layer = None
            return self
        # Hardcoded override: TCL by driver always needs "driver" intersection
        elif dataset_id == TREE_COVER_LOSS_BY_DRIVER_ID:
            self.context_layer = "driver"
            return self

        if self.context_layer is None:
            return self

        selected_dataset = [
            ds for ds in DATASETS if ds["dataset_id"] == dataset_id
        ][0]
        context_layers = selected_dataset.get("context_layers") or []
        context_layer_values = [lyr["value"] for lyr in context_layers]
        if self.context_layer not in context_layer_values:
            self.context_layer = None

        return self
    