"""
Type definitions for E2E testing framework.
"""

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, field_validator


class TestResult(BaseModel):
    """Result of a single E2E test execution."""

    model_config = ConfigDict(extra="allow")

    thread_id: str
    trace_id: Optional[str] = None
    trace_url: Optional[str] = None
    query: str
    overall_score: float
    execution_time: str
    test_mode: str

    # AOI evaluation fields
    aoi_score: Optional[float] = None
    actual_id: Optional[str] = None
    actual_name: Optional[str] = None
    actual_subtype: Optional[str] = None
    actual_source: Optional[str] = None
    actual_subregion: Optional[str] = None
    match_aoi_id: bool = False
    match_subregion: bool = False

    # Dataset evaluation fields
    dataset_score: Optional[float] = None
    actual_dataset_id: Optional[str] = None
    actual_dataset_name: Optional[str] = None
    actual_context_layer: Optional[str] = None

    # Data pull evaluation fields
    pull_data_score: Optional[float] = None
    row_count: int = 0
    min_rows: int = 1
    data_pull_success: bool = False
    date_success: bool = False
    actual_start_date: Optional[str] = None
    actual_end_date: Optional[str] = None

    # Answer evaluation fields
    answer_score: Optional[float] = None
    actual_answer: Optional[str] = None

    # Expected data fields
    expected_aoi_ids: List[str] = []
    expected_subregion: str = ""
    expected_aoi_source: str = ""
    expected_dataset_id: str = ""
    expected_dataset_name: str = ""
    expected_context_layer: str = ""
    expected_start_date: str = ""
    expected_end_date: str = ""
    expected_answer: str = ""
    test_group: str = "unknown"
    status: str = "ready"

    # Error handling
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for CSV export."""
        return self.model_dump(exclude_none=False)


class ExpectedData(BaseModel):
    """Expected test data for evaluation."""

    model_config = ConfigDict(extra="allow")

    expected_aoi_ids: List[str] = []
    expected_subregion: str = ""
    expected_aoi_source: str = ""
    expected_dataset_id: str = ""
    expected_dataset_name: str = ""
    expected_context_layer: str = ""
    expected_start_date: str = ""
    expected_end_date: str = ""
    expected_answer: str = ""
    test_group: str = "unknown"
    status: str = "ready"
    thread_id: Optional[str] = None

    @field_validator("expected_aoi_ids", mode="before")
    @classmethod
    def split_aoi_ids(cls, v: Union[str, List[str]]) -> List[str]:
        """Split string input into a list of strings."""
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            # Split by comma and strip whitespace, filter out empty strings
            return [item.strip() for item in v.split(";") if item.strip()]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return self.model_dump(exclude_none=False)
