"""Pydantic models for one trial: ``ExpectedData`` (a case's expectations) and
``TestResult`` (the scores and diagnostics it produced)."""

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


def _parse_tri_state_bool(v: str | bool | None) -> bool | None:
    """Convert string input to boolean or None.

    - Empty string "" -> None (no expectation)
    - "false", "False", "0", "no" -> False
    - "true", "True", "1", "yes" -> True
    - Boolean values pass through unchanged
    - Any other string -> None (no expectation)
    """
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        if not v or v.strip() == "":
            return None
        if v.lower() in ("false", "0", "no"):
            return False
        if v.lower() in ("true", "1", "yes"):
            return True
        return None
    return bool(v) if v else None


class TestResult(BaseModel):
    """Scores and diagnostics from one trial of a case (or of one turn)."""

    model_config = ConfigDict(extra="allow")

    thread_id: str
    app_thread_url: str | None = None
    trace_id: str | None = None
    trace_url: str | None = None
    test_id: str = ""
    query: str
    eval_set: str = "custom"
    overall_score: float
    execution_time: str
    duration_seconds: float | None = None

    # AOI evaluation fields: separate binary scores (0/1/None)
    aoi_id_match_score: float | None = None
    actual_id: str | None = None
    actual_name: str | None = None
    actual_subtype: str | None = None
    actual_source: str | None = None
    match_aoi_id: bool = False

    # Dataset evaluation fields: separate binary scores (0/1/None)
    dataset_id_match_score: float | None = None
    dataset_parameter_match_score: float | None = None
    context_layer_match_score: float | None = None
    actual_dataset_id: str | None = None
    actual_dataset_name: str | None = None
    actual_dataset_parameters: str | None = None
    actual_context_layer: str | None = None

    # Data pull evaluation fields: separate binary scores (0/1/None)
    data_pull_exists_score: float | None = None
    date_coverage_score: float | None = None
    date_extraction_score: float | None = None
    actual_extracted_start_date: str | None = None
    actual_extracted_end_date: str | None = None
    date_extraction_source: str | None = None
    actual_extracted_windows: str | None = None
    row_count: int = 0
    min_rows: int = 1
    data_pull_success: bool = False
    data_pull_error: str = ""
    date_success: bool | None = None
    actual_start_date: str | None = None
    actual_end_date: str | None = None

    # Answer evaluation fields
    charts_answer_score: float | None = None
    # The chart judge's own appropriateness verdict: reported, never gating.
    charts_answer_judge_score: float | None = None
    chart_answer_score_reason: str | None = None
    agent_answer_score: float | None = None
    agent_answer_score_reason: str | None = None
    expected_text_match_score: float | None = None
    expected_text_match_score_reason: str | None = None
    actual_charts_answer: str | None = None
    actual_charts_json: str | None = None
    actual_agent_answer: str | None = None
    actual_codeact_summary: str | None = None

    # Clarification evaluation fields
    actual_clarification_requested: bool | None = None
    clarification_requested_score: float | None = None

    # Suggested datasets evaluation fields
    suggested_datasets_match_score: float | None = None
    actual_suggested_datasets: str | None = None

    # Nudge evaluation fields
    nudge_match_score: float | None = None
    actual_nudge_type: str | None = None
    actual_nudge_options: str | None = None

    # Dashboard evaluation fields
    dashboard_created_score: float | None = None
    actual_dashboard_created: bool | None = None
    actual_dashboard_id: str | None = None
    dashboard_aoi_match_score: float | None = None
    actual_dashboard_aoi_count: int | None = None
    actual_dashboard_aoi_id: str | None = None
    actual_dashboard_aoi_source: str | None = None
    dashboard_widgets_match_score: float | None = None
    actual_dashboard_widget_types: str | None = None
    dashboard_widgets_valid_score: float | None = None

    # Ground-truth evaluation fields
    ground_truth_match_score: float | None = None
    ground_truth_match_score_reason: str | None = None
    agent_ground_truth: str | None = None
    agent_ground_truth_values: list[float | None] | None = None
    ground_truth_answer_score: float | None = None
    ground_truth_answer_score_reason: str | None = None
    agent_ground_truth_answer: str | None = None

    # Expected data fields
    expected_aoi_ids: list[str] | None = None
    expected_aoi_source: str = ""
    expected_dataset_id: str = ""
    expected_dataset_name: str = ""
    expected_dataset_parameters: str = ""
    expected_context_layer: str = ""
    expected_start_date: str = ""
    expected_end_date: str = ""
    expected_answer: str = ""
    expected_text: str = ""
    expected_clarification: bool | None = None
    expected_suggested_datasets: list[str] = []
    expected_dashboard_created: bool | None = None
    expected_dashboard_widgets: list[str] | None = None
    expected_nudge_type: str = ""
    expected_nudge_options: list[str] = []
    test_group: str = "unknown"
    status: str = "ready"

    # Error handling
    error: str | None = None

    # Unused: num_trials and the *_score_std fields below are never set. Trials
    # are merged per check, by majority, in cli.merge_trials.
    num_trials: int = 1

    overall_score_std: float | None = None
    aoi_id_match_score_std: float | None = None
    dataset_id_match_score_std: float | None = None
    dataset_parameter_match_score_std: float | None = None
    context_layer_match_score_std: float | None = None
    data_pull_exists_score_std: float | None = None
    date_coverage_score_std: float | None = None
    date_extraction_score_std: float | None = None
    charts_answer_score_std: float | None = None
    charts_answer_judge_score_std: float | None = None
    agent_answer_score_std: float | None = None
    expected_text_match_score_std: float | None = None
    clarification_requested_score_std: float | None = None
    suggested_datasets_match_score_std: float | None = None
    dashboard_created_score_std: float | None = None
    dashboard_aoi_match_score_std: float | None = None
    dashboard_widgets_match_score_std: float | None = None
    dashboard_widgets_valid_score_std: float | None = None
    nudge_match_score_std: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Plain dict of every field, including None values."""
        return self.model_dump(exclude_none=False)


class ExpectedData(BaseModel):
    """Expected test data for evaluation."""

    model_config = ConfigDict(extra="allow")

    expected_aoi_ids: list[str] | None = None
    expected_aoi_source: str = ""
    expected_dataset_id: str = ""
    expected_dataset_name: str = ""
    expected_dataset_parameters: str = ""
    expected_context_layer: str = ""
    expected_start_date: str = ""
    expected_end_date: str = ""
    expected_answer: str = ""
    expected_text: str = ""
    expected_clarification: bool | None = None
    expected_suggested_datasets: list[str] = []
    expected_dashboard_created: bool | None = None
    expected_dashboard_widgets: list[str] | None = None
    expected_nudge_type: str = ""
    expected_nudge_options: list[str] = []
    expected_ground_truth: str = ""  # the selector, from the case
    ground_truth_values: list[float] = []  # fetched at run start, not from the case,
    ground_truth_unresolved: str = ""  # so deliberately unprefixed
    expected_chart_type: str = ""
    expected_scope: str = ""
    expected_class_values: str = ""
    test_id: str = ""
    test_group: str = "unknown"
    status: str = "ready"

    @field_validator("expected_dashboard_widgets", mode="before")
    @classmethod
    def split_dashboard_widgets(cls, v: str | list[str] | None) -> list[str] | None:
        """Split semicolon-separated widget types into a list of strings."""
        if v is None:
            return None
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            items = [item.strip() for item in v.split(";") if item.strip()]
            return items or None
        return None

    @field_validator("expected_suggested_datasets", mode="before")
    @classmethod
    def split_suggested_datasets(cls, v: str | list[str]) -> list[str]:
        """Split semicolon-separated string input into a list of strings."""
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            if v.strip() in ("", "[]"):
                return []
            return [item.strip() for item in v.split(";") if item.strip()]
        return []

    @field_validator("expected_aoi_ids", mode="before")
    @classmethod
    def split_aoi_ids(cls, v: str | list[str]) -> list[str]:
        """Split semicolon-separated AOI ids into a list; the agent must select
        exactly this set (the ids are not alternatives)."""
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            return [item.strip() for item in v.split(";") if item.strip()]
        return []

    @field_validator("expected_nudge_options", mode="before")
    @classmethod
    def split_nudge_options(cls, v: str | list[str]) -> list[str]:
        """Split semicolon-separated string input into a list of strings."""
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            if v.strip() in ("", "[]"):
                return []
            return [item.strip() for item in v.split(";") if item.strip()]
        return []

    @field_validator("expected_clarification", mode="before")
    @classmethod
    def parse_clarification(cls, v: str | bool | None) -> bool | None:
        """Convert string input to boolean or None (tri-state: True/False/no-expectation)."""
        return _parse_tri_state_bool(v)

    @field_validator("expected_dashboard_created", mode="before")
    @classmethod
    def parse_dashboard_created(cls, v: str | bool | None) -> bool | None:
        """Convert string input to boolean or None (tri-state: True/False/no-expectation)."""
        return _parse_tri_state_bool(v)

    def expects_data_pull(self) -> bool:
        """Return whether the agent should pull analytics data for this test.

        Gold-set rows require a data pull when ``expected_answer`` is set
        (chart/insight answers depend on pulled statistics). Dashboard rows
        require a data pull when ``expected_dashboard_widgets`` includes
        ``insight``; map-only dashboard rows do not. A ``ground_truth`` row
        grades the agent's pull itself, so it requires one too.
        """
        if self.expected_clarification is True:
            return False
        if self.expected_answer or self.expected_ground_truth:
            return True
        widgets = self.expected_dashboard_widgets or []
        return "insight" in widgets

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return self.model_dump(exclude_none=False)
