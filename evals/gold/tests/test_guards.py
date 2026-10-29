"""Tests for the guard checks in `evaluators/guards.py` and the slow-row
latency flag.

Test-name prefixes map to checks: g1 `answered_without_data`, g2
`web_fallback`, g3 the latency flag (`goldset.cli.latency_info`), g4
`pull_source_match`, f2 `chart_produced`.

The `statistics` fixture copies the entry shape seen in 84 staging
artefacts that carried a data pull: `source_url` names the dataset by
slug, and `dataset_id` is an int present on most entries (81 of 84) but
not all.
"""

from types import SimpleNamespace

from goldset.cli import latency_info
from goldset.evaluators.guards import evaluate_guards

LONG_ANSWER = (
    "Based on WRI's mangrove statistics, Fatick has substantially more "
    "mangrove area than Ziguinchor, with extensive estuarine systems. "
    "See https://www.wri.org/insights/mangroves for background."
)


def state(answer=None, stats=None, dataset_id=None, charts=None):
    return {
        "messages": [SimpleNamespace(content=answer)] if answer else [],
        "statistics": stats if stats is not None else [],
        "dataset": {"dataset_id": dataset_id} if dataset_id else {},
        "charts_data": charts or [],
    }


PULL = [
    {
        "source_url": "https://analytics.globalnaturewatch.org/v0/land_change/"
        "dist_alerts/analytics",
        "id": "01998037-a63a-7c39-b52c-b6e112bb4d4d",
        "data": [{"year": 2024, "area_ha": 1.0}],
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
        "dataset_id": 11,
        "dataset_name": "Integrated alerts",
    }
]


def test_g1_answered_without_data_catches_1_030_shape():
    result = evaluate_guards(
        state(answer=LONG_ANSWER),
        expects_data_pull=True,
        expected_answer="Fatick",
        expected_dataset_id="3",
    )
    assert result["answered_without_data_score"] == 0.0


def test_g1_clean_when_data_pulled():
    result = evaluate_guards(
        state(answer=LONG_ANSWER, stats=PULL, dataset_id="3"),
        expects_data_pull=True,
        expected_answer="Fatick",
        expected_dataset_id="3",
    )
    assert result["answered_without_data_score"] == 1.0


def test_g1_refusal_is_not_a_violation():
    result = evaluate_guards(
        state(answer="I can't answer that."),
        expects_data_pull=True,
        expected_answer="x",
        expected_dataset_id="",
    )
    assert result["answered_without_data_score"] == 1.0


def test_g1_not_applicable_without_pull_expectation():
    result = evaluate_guards(
        state(answer=LONG_ANSWER),
        expects_data_pull=False,
        expected_answer="",
        expected_dataset_id="",
    )
    assert result["answered_without_data_score"] is None


def test_f2_chart_produced():
    absent = evaluate_guards(
        state(answer="prose only", stats=PULL),
        expects_data_pull=True,
        expected_answer="42 ha",
        expected_dataset_id="",
    )
    assert absent["chart_produced_score"] == 0.0
    present = evaluate_guards(
        state(answer="prose", stats=PULL, charts=[{"type": "bar", "data": []}]),
        expects_data_pull=True,
        expected_answer="42 ha",
        expected_dataset_id="",
    )
    assert present["chart_produced_score"] == 1.0
    no_expectation = evaluate_guards(
        state(answer="prose"),
        expects_data_pull=False,
        expected_answer="",
        expected_dataset_id="",
    )
    assert no_expectation["chart_produced_score"] is None


def test_f2_chart_produced_exempts_clarification_rows():
    # expected_answer set but expects_data_pull() False (a clarification
    # row): the guard defers, matching its siblings' gate.
    result = evaluate_guards(
        state(answer="Which Fatick did you mean?"),
        expects_data_pull=False,
        expected_answer="42 ha",
        expected_dataset_id="",
    )
    assert result["chart_produced_score"] is None


def test_g3_latency_info_threshold():
    assert latency_info(180.1, 180.0) == {"slow": True, "threshold_s": 180.0}
    assert latency_info(10.0, 180.0) is None
    assert latency_info(180.0, 180.0) is None  # boundary: strictly over flags
    assert latency_info(None, 180.0) is None  # no recorded latency


def test_g2_web_fallback_flags_external_links_only():
    external = evaluate_guards(
        state(answer=LONG_ANSWER, stats=PULL, dataset_id="3"),
        expects_data_pull=True,
        expected_answer="x",
        expected_dataset_id="3",
    )
    assert external["web_fallback_score"] == 0.0
    assert "wri.org" in external["actual_web_links"]

    own = evaluate_guards(
        state(
            answer="See https://app.globalnaturewatch.org/threads/x for the map. "
            + "A" * 60,
            stats=PULL,
            dataset_id="3",
        ),
        expects_data_pull=True,
        expected_answer="x",
        expected_dataset_id="3",
    )
    assert own["web_fallback_score"] == 1.0


def test_g4_pull_source_match_and_abstention():
    # dataset_id is an int on real entries; normalize_value bridges the
    # comparison with the case's string expectation.
    match = evaluate_guards(
        state(answer="a" * 100, stats=[{**PULL[0], "dataset_id": 11}]),
        expects_data_pull=True,
        expected_answer="x",
        expected_dataset_id="11",
    )
    assert match["pull_source_match_score"] == 1.0
    assert match["actual_pull_source"] == "11"

    mismatch = evaluate_guards(
        state(answer="a" * 100, stats=[{**PULL[0], "dataset_id": 4}]),
        expects_data_pull=True,
        expected_answer="x",
        expected_dataset_id="11",
    )
    assert mismatch["pull_source_match_score"] == 0.0

    # the 3/84 real shape without a dataset_id key: abstain, auditable. The
    # diagnostic carries the source_url/id the guard saw.
    entry = {k: v for k, v in PULL[0].items() if k != "dataset_id"}
    unreadable = evaluate_guards(
        state(answer="a" * 100, stats=[entry]),
        expects_data_pull=True,
        expected_answer="x",
        expected_dataset_id="11",
    )
    assert unreadable["pull_source_match_score"] is None
    assert "abstained" in unreadable["actual_pull_source"]
    assert "land_change" in unreadable["actual_pull_source"]


def test_g4_dataset_id_zero_is_a_real_reference():
    # 0 is a real dataset id. A truthiness read such as `get(...) or ...`
    # would treat it as missing and abstain.
    result = evaluate_guards(
        state(answer="a" * 100, stats=[{**PULL[0], "dataset_id": 0}]),
        expects_data_pull=True,
        expected_answer="x",
        expected_dataset_id="0",
    )
    assert result["pull_source_match_score"] == 1.0


def test_g4_never_token_matches_numeric_ids_against_source_url():
    # "11" appears in the url only as a date fragment; without an explicit
    # dataset_id the guard must abstain, never token-match the url: real
    # urls identify datasets by slug, so any numeric hit is spurious.
    entry = {k: v for k, v in PULL[0].items() if k != "dataset_id"}
    entry["source_url"] += "?start_date=2024-11-01&end_date=2024-11-30"
    result = evaluate_guards(
        state(answer="a" * 100, stats=[entry]),
        expects_data_pull=True,
        expected_answer="x",
        expected_dataset_id="11",
    )
    assert result["pull_source_match_score"] is None


def test_guards_flow_through_registry():
    from goldset.eval_types import ExpectedData
    from goldset.runner.base import BaseTestRunner

    class _Probe(BaseTestRunner):
        async def run_test(self, query, expected_data):  # pragma: no cover
            raise NotImplementedError

    evaluations = _Probe()._run_evaluations(
        state(answer=LONG_ANSWER),
        ExpectedData(expected_answer="Fatick has more"),
        "which state has more mangroves?",
        None,
    )
    assert evaluations["answered_without_data_score"] == 0.0
    assert evaluations["chart_produced_score"] == 0.0
    assert evaluations["web_fallback_score"] == 0.0
