"""Tests for the evaluator registry (goldset.registry): evaluators run in a
fixed order, each score field has exactly one owner, and a case with no
expectations scores nothing and calls no LLM judge."""

from goldset.eval_types import ExpectedData
from goldset.registry import ALL_SCORE_FIELDS, EVALUATORS
from goldset.runner.base import BaseTestRunner


class _Probe(BaseTestRunner):
    async def run_test(self, query, expected_data):  # pragma: no cover
        raise NotImplementedError


EXPECTED_ORDER = (
    "clarification",
    "aoi",
    "dataset",
    "date_coverage",
    "date_extraction",
    "data_pull",
    "answer",
    "ground_truth",
    "suggested_datasets",
    "nudge",
    "dashboard_created",
    "dashboard_aoi",
    "dashboard_widgets",
    "guards",
    "analysis_checks",
    "traceability",
    "output_checks",
    "scope",
)


def test_registry_order_matches_legacy_merge_order():
    assert tuple(spec.name for spec in EVALUATORS) == EXPECTED_ORDER


def test_every_known_score_field_is_owned_exactly_once():
    # Pinned so that adding or removing a score field is a deliberate,
    # visible edit.
    assert len(ALL_SCORE_FIELDS) == len(set(ALL_SCORE_FIELDS)) == 30


def test_run_evaluations_with_no_expectations_scores_nothing():
    """No expected values -> every score None, and (critically) no judge is
    invoked, so this test passes with no ANTHROPIC_API_KEY."""
    runner = _Probe()
    evaluations = runner._run_evaluations(
        agent_state={"messages": [], "charts_data": []},
        expected_data=ExpectedData(),
        query="anything",
        dashboard=None,
    )
    for field in ALL_SCORE_FIELDS:
        assert evaluations.get(field) is None, field


def test_deterministic_scores_flow_through_registry():
    runner = _Probe()
    state = {
        "aoi_selection": {
            "aois": [
                {
                    "src_id": "BRA.25_1",
                    "name": "São Paulo",
                    "subtype": "state",
                    "source": "gadm",
                }
            ]
        },
        "dataset": {
            "dataset_id": "11",
            "dataset_name": "Integrated alerts",
            "parameters": [],
            "context_layer": None,
        },
        "messages": [],
        "charts_data": [],
    }
    expected = ExpectedData(expected_aoi_ids="BRA.25_1", expected_dataset_id="11")
    evaluations = runner._run_evaluations(state, expected, "q", None)
    assert evaluations["aoi_id_match_score"] == 1.0
    assert evaluations["dataset_id_match_score"] == 1.0
    assert runner._calculate_overall_score(evaluations, expected) == 1.0
