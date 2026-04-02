from typing import Optional

from pydantic import Field

from src.agent.tools.models.dataset_option import DatasetOption


class DatasetSelectionResult(DatasetOption):
    tile_url: str = Field(
        description="Tile URL of the dataset that best matches the user query.",
    )
    dataset_name: str = Field(
        description="Name of the dataset that best matches the user query."
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
    # Tiered instruction fields (PoC) — None for datasets that haven't been migrated
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
