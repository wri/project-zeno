"""
Type definitions for E2E testing framework.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


@dataclass
class TestResult:
    """Result of a single E2E test execution."""

    thread_id: str
    trace_id: Optional[str]
    trace_url: Optional[str]
    query: str
    overall_score: float
    execution_time: str
    test_mode: str

    # AOI evaluation fields
    aoi_score: float
    actual_id: Optional[str]
    actual_name: Optional[str]
    actual_subtype: Optional[str]
    actual_source: Optional[str]
    actual_subregion: Optional[str]
    match_aoi_id: bool
    match_subregion: bool

    # Dataset evaluation fields
    dataset_score: float
    actual_dataset_id: Optional[str]
    actual_dataset_name: Optional[str]
    actual_context_layer: Optional[str]

    # Data pull evaluation fields
    pull_data_score: float
    row_count: int
    min_rows: int
    data_pull_success: bool
    date_success: bool
    actual_start_date: Optional[str]
    actual_end_date: Optional[str]

    # Answer evaluation fields
    answer_score: float
    actual_answer: Optional[str]

    # Expected data fields
    expected_aoi_ids: List[str] = Field(default_factory=list)
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
        return {
            "thread_id": self.thread_id,
            "trace_id": self.trace_id,
            "trace_url": self.trace_url,
            "query": self.query,
            "overall_score": self.overall_score,
            "execution_time": self.execution_time,
            "test_mode": self.test_mode,
            "aoi_score": self.aoi_score,
            "actual_id": self.actual_id,
            "actual_name": self.actual_name,
            "actual_subtype": self.actual_subtype,
            "actual_source": self.actual_source,
            "actual_subregion": self.actual_subregion,
            "match_aoi_id": self.match_aoi_id,
            "match_subregion": self.match_subregion,
            "dataset_score": self.dataset_score,
            "actual_dataset_id": self.actual_dataset_id,
            "actual_dataset_name": self.actual_dataset_name,
            "actual_context_layer": self.actual_context_layer,
            "pull_data_score": self.pull_data_score,
            "row_count": self.row_count,
            "min_rows": self.min_rows,
            "data_pull_success": self.data_pull_success,
            "date_success": self.date_success,
            "actual_start_date": self.actual_start_date,
            "actual_end_date": self.actual_end_date,
            "answer_score": self.answer_score,
            "actual_answer": self.actual_answer,
            "expected_aoi_ids": self.expected_aoi_ids,
            "expected_subregion": self.expected_subregion,
            "expected_aoi_source": self.expected_aoi_source,
            "expected_dataset_id": self.expected_dataset_id,
            "expected_dataset_name": self.expected_dataset_name,
            "expected_context_layer": self.expected_context_layer,
            "expected_start_date": self.expected_start_date,
            "expected_end_date": self.expected_end_date,
            "expected_answer": self.expected_answer,
            "test_group": self.test_group,
            "status": self.status,
            "error": self.error,
        }


class ExpectedData(BaseModel):
    """Expected test data for evaluation."""

    model_config = ConfigDict(extra="allow")

    expected_aoi_ids: List[str] = []
    expected_subregion: str = ""
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
