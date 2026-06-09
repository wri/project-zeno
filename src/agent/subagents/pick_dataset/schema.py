from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from src.agent.datasets.config import DATASETS
from src.agent.datasets.handlers.analytics_handler import (
    TREE_COVER_LOSS_BY_DRIVER_ID,
)


class DatasetParameter(BaseModel):
    name: str
    description: str
    values: List[Any]


class ContextLayer(BaseModel):
    name: str
    tile_url: Optional[str]
    source_layer: Optional[str]


class DatasetOption(BaseModel):
    dataset_id: Optional[int] = Field(
        None,
        description="ID of the dataset that best matches the user query. Set to null if no candidate is a good fit.",
    )
    context_layer: Optional[str] = Field(
        None,
        description="Context layer to apply. Follow the context layer descriptions — select the layer whose description matches the query, and always select one when a description says to default to it for the query type.",
    )
    parameters: Optional[list[DatasetParameter]] = Field(
        None, description="Dataset specific parameters."
    )
    start_date: Optional[str] = Field(
        None,
        description="User defined start date truncated to the dataset's available range.",
    )
    end_date: Optional[str] = Field(
        None,
        description="User defined end date truncated to the dataset's available range.",
    )
    reason: str = Field(
        description="Short reason why the dataset is the best match."
    )

    @field_validator("dataset_id")
    def validate_dataset_id(cls, v):
        if v is None:
            return v
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

    @model_validator(mode="after")
    def validate_parameters_for_dataset(self) -> "DatasetOption":
        """Ensure parameters and their chosen values are valid for the chosen dataset_id."""
        dataset_id = self.dataset_id
        if dataset_id is None or self.parameters is None:
            self.parameters = None
            return self

        selected_dataset = [
            ds for ds in DATASETS if ds["dataset_id"] == dataset_id
        ][0]
        dataset_parameters = selected_dataset.get("parameters") or []
        allowed_parameters = {
            param["name"]: param for param in dataset_parameters
        }

        validated_parameters = []
        for parameter in self.parameters:
            allowed_parameter = allowed_parameters.get(parameter.name)
            if allowed_parameter is None:
                continue

            allowed_values = allowed_parameter.get("values") or []
            valid_values = [
                value for value in parameter.values if value in allowed_values
            ]
            if not valid_values:
                continue

            validated_parameters.append(
                DatasetParameter(
                    name=parameter.name,
                    description=parameter.description,
                    values=valid_values,
                )
            )

        self.parameters = validated_parameters or None
        return self


class DatasetSelectionResponse(BaseModel):
    selected_dataset: Optional[DatasetOption] = None
    suggested_datasets: Optional[list[DatasetOption]] = Field(
        None, max_length=3
    )
    reason: str = Field(
        description="Explain what datasets were considered, what each covers, and specifically why no single one directly answers the query. Name the datasets evaluated and describe where each falls short."
    )


class DatasetSelectionResult(DatasetOption):
    tile_url: str = Field(
        description="Tile URL of the dataset that best matches the user query.",
    )
    dataset_name: str = Field(
        description="Name of the dataset that best matches the user query."
    )
    context_layers: list[ContextLayer] = Field(
        [],
        description="Metadata for selected context layers.",
    )
    analytics_api_endpoint: str = Field(
        description="Analytics API endpoint of the dataset that best matches the user query.",
    )
    description: str = Field(
        description="Description of the dataset that best matches the user query.",
    )
    prompt_instructions: str = Field(
        description="Prompt instructions of the dataset that best matches the user query.",
    )
    methodology: str = Field(
        description="Methodology of the dataset that best matches the user query.",
    )
    cautions: str = Field(
        description="Cautions of the dataset that best matches the user query.",
    )
    function_usage_notes: str = Field(
        description="Function usage notes of the dataset that best matches the user query.",
    )
    citation: str = Field(
        description="Citation of the dataset that best matches the user query.",
    )
    content_date: str = Field(
        description="Content date of the dataset that best matches the user query.",
    )
    # Tiered instruction fields (PoC) - None for datasets that haven't been migrated
    selection_hints: Optional[str] = Field(
        default=None,
        description="When to prefer this dataset over alternatives.",
    )
    code_instructions: Optional[str] = Field(
        default=None,
        description="Chart type restrictions and data shaping rules for the code executor.",
    )
    presentation_instructions: Optional[str] = Field(
        default=None,
        description="Terminology, tone, and how to describe results to users.",
    )
