"""Evaluator registry: the ordered list of evaluators run on every agent state.

The runner calls each spec in order and merges the result dicts, so a later
evaluator overwrites an earlier one's key on a collision. Keep the order
stable.

Bucket membership is not declared here. Tag every new score field in
``buckets.py`` (``DEDICATED``, ``SHARED`` or ``INFO_ONLY``);
``tests/test_buckets.py`` fails if one is missing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from goldset.eval_types import ExpectedData
from goldset.evaluators import (
    evaluate_aoi_selection,
    evaluate_clarification,
    evaluate_dashboard_aoi,
    evaluate_dashboard_created,
    evaluate_dashboard_widgets,
    evaluate_data_pull,
    evaluate_dataset_selection,
    evaluate_date_extraction,
    evaluate_date_selection,
    evaluate_final_answer,
    evaluate_nudge,
    evaluate_suggested_datasets,
)
from goldset.evaluators.analysis_checks import (
    evaluate_chart_integrity,
    evaluate_class_values,
)
from goldset.evaluators.explanation_checks import evaluate_answer_traceability
from goldset.evaluators.groundtruth_checks import evaluate_ground_truth
from goldset.evaluators.guards import evaluate_guards
from goldset.evaluators.output_checks import (
    evaluate_chart_type,
    evaluate_chart_well_formed,
)
from goldset.evaluators.scope_checks import evaluate_scope

EvaluatorFn = Callable[
    [dict[str, Any], ExpectedData, str, dict[str, Any] | None],
    dict[str, Any],
]


@dataclass(frozen=True)
class EvaluatorSpec:
    name: str
    kind: str  # "deterministic" | "llm_judge" | "mixed"
    score_fields: tuple[str, ...]
    run: EvaluatorFn


EVALUATORS: tuple[EvaluatorSpec, ...] = (
    EvaluatorSpec(
        name="clarification",
        kind="llm_judge",
        score_fields=("clarification_requested_score",),
        run=lambda state, expected, query, dashboard: evaluate_clarification(
            state, expected.expected_clarification, query
        ),
    ),
    EvaluatorSpec(
        name="aoi",
        kind="deterministic",
        score_fields=("aoi_id_match_score",),
        run=lambda state, expected, query, dashboard: evaluate_aoi_selection(
            state, expected.expected_aoi_ids, query
        ),
    ),
    EvaluatorSpec(
        name="dataset",
        kind="deterministic",
        score_fields=(
            "dataset_id_match_score",
            "dataset_parameter_match_score",
            "context_layer_match_score",
        ),
        run=lambda state, expected, query, dashboard: evaluate_dataset_selection(
            state,
            expected.expected_dataset_id,
            expected.expected_dataset_parameters,
            expected.expected_context_layer,
            query,
        ),
    ),
    EvaluatorSpec(
        name="date_coverage",
        kind="deterministic",
        score_fields=("date_coverage_score",),
        run=lambda state, expected, query, dashboard: evaluate_date_selection(
            state,
            expected_start_date=expected.expected_start_date,
            expected_end_date=expected.expected_end_date,
        ),
    ),
    EvaluatorSpec(
        name="date_extraction",
        kind="deterministic",
        score_fields=("date_extraction_score",),
        run=lambda state, expected, query, dashboard: evaluate_date_extraction(
            state,
            expected_start_date=expected.expected_start_date,
            expected_end_date=expected.expected_end_date,
        ),
    ),
    EvaluatorSpec(
        name="data_pull",
        kind="deterministic",
        score_fields=("data_pull_exists_score",),
        run=lambda state, expected, query, dashboard: evaluate_data_pull(
            state, expects_data_pull=expected.expects_data_pull(), query=query
        ),
    ),
    EvaluatorSpec(
        name="answer",
        kind="mixed",
        score_fields=(
            "charts_answer_score",
            "charts_answer_judge_score",
            "agent_answer_score",
            "expected_text_match_score",
        ),
        run=lambda state, expected, query, dashboard: evaluate_final_answer(
            state, expected.expected_answer, expected.expected_text, query
        ),
    ),
    EvaluatorSpec(
        name="ground_truth",
        kind="mixed",
        score_fields=("ground_truth_match_score", "ground_truth_answer_score"),
        run=lambda state, expected, query, dashboard: evaluate_ground_truth(
            state, expected
        ),
    ),
    EvaluatorSpec(
        name="suggested_datasets",
        kind="deterministic",
        score_fields=("suggested_datasets_match_score",),
        run=lambda state, expected, query, dashboard: evaluate_suggested_datasets(
            state, expected.expected_suggested_datasets
        ),
    ),
    EvaluatorSpec(
        name="nudge",
        kind="deterministic",
        score_fields=("nudge_match_score",),
        run=lambda state, expected, query, dashboard: evaluate_nudge(
            state, expected.expected_nudge_type, expected.expected_nudge_options
        ),
    ),
    EvaluatorSpec(
        name="dashboard_created",
        kind="deterministic",
        score_fields=("dashboard_created_score",),
        run=lambda state, expected, query, dashboard: evaluate_dashboard_created(
            state, expected.expected_dashboard_created
        ),
    ),
    EvaluatorSpec(
        name="dashboard_aoi",
        kind="deterministic",
        score_fields=("dashboard_aoi_match_score",),
        run=lambda state, expected, query, dashboard: evaluate_dashboard_aoi(
            dashboard, expected.expected_aoi_ids, expected.expected_aoi_source
        ),
    ),
    EvaluatorSpec(
        name="dashboard_widgets",
        kind="deterministic",
        score_fields=(
            "dashboard_widgets_match_score",
            "dashboard_widgets_valid_score",
        ),
        run=lambda state, expected, query, dashboard: evaluate_dashboard_widgets(
            dashboard, expected.expected_dashboard_widgets
        ),
    ),
    EvaluatorSpec(
        name="guards",
        kind="deterministic",
        score_fields=(
            "chart_produced_score",
            "answered_without_data_score",
            "web_fallback_score",
            "pull_source_match_score",
        ),
        run=lambda state, expected, query, dashboard: evaluate_guards(
            state,
            expects_data_pull=expected.expects_data_pull(),
            expected_answer=expected.expected_answer,
            expected_dataset_id=expected.expected_dataset_id,
        ),
    ),
    EvaluatorSpec(
        name="analysis_checks",
        kind="deterministic",
        score_fields=("class_value_match_score", "chart_integrity_score"),
        run=lambda state, expected, query, dashboard: {
            **evaluate_class_values(state, expected.expected_class_values),
            **evaluate_chart_integrity(state),
        },
    ),
    EvaluatorSpec(
        name="traceability",
        kind="deterministic",
        score_fields=("answer_traceability_score",),
        run=lambda state, expected, query, dashboard: (
            evaluate_answer_traceability(state)
        ),
    ),
    EvaluatorSpec(
        name="output_checks",
        kind="deterministic",
        score_fields=("chart_well_formed_score", "chart_type_match_score"),
        run=lambda state, expected, query, dashboard: {
            **evaluate_chart_well_formed(state),
            **evaluate_chart_type(state, expected.expected_chart_type),
        },
    ),
    EvaluatorSpec(
        name="scope",
        kind="deterministic",
        score_fields=("scope_match_score",),
        run=lambda state, expected, query, dashboard: evaluate_scope(
            state, expected.expected_scope
        ),
    ),
)

EVALUATOR_NAMES: frozenset[str] = frozenset(spec.name for spec in EVALUATORS)

ALL_SCORE_FIELDS: tuple[str, ...] = tuple(
    field for spec in EVALUATORS for field in spec.score_fields
)
