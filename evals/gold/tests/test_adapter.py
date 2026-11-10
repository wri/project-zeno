"""Case -> ExpectedData adaptation: prefixing, parsing, uid passthrough."""

from goldset.adapter import case_to_expected
from goldset.store import Case

CASE = Case(
    id="1-002",
    status="todo",
    group="direct",
    query="Sao Paulo disturbance in H2 2024?",
    expected={
        "aoi_ids": "BRA.25_1;BRA.14_1",
        "dataset_id": "11",
        "answer": "1,319,600 hectares",
        "clarification": "FALSE",
        "suggested_datasets": "0;11",
        "dashboard_widgets": "insight;map",
    },
    notes={"status_reason": "irrelevant to the harness"},
)


def test_prefixing_and_validator_parsing():
    expected = case_to_expected(CASE)
    assert expected.expected_dataset_id == "11"
    assert expected.expected_answer == "1,319,600 hectares"
    # ExpectedData's own validators apply, identically to gnw-evals:
    assert expected.expected_aoi_ids == ["BRA.25_1", "BRA.14_1"]
    assert expected.expected_clarification is False
    assert expected.expected_suggested_datasets == ["0", "11"]
    assert expected.expected_dashboard_widgets == ["insight", "map"]


def test_metadata_and_uid_ride_along():
    expected = case_to_expected(CASE)
    assert expected.test_id == "1-002"
    assert expected.test_group == "direct"
    assert expected.status == "todo"
    assert expected.uid == CASE.uid  # extra="allow" passthrough


def test_absent_fields_take_harness_defaults():
    bare = Case(id="x", status="ready", group="g", query="q")
    expected = case_to_expected(bare)
    assert expected.expected_answer == ""
    assert expected.expected_clarification is None
    assert expected.expects_data_pull() is False


def test_expects_data_pull_gating():
    assert case_to_expected(CASE).expects_data_pull() is True
    clarify = Case(
        id="y",
        status="ready",
        group="g",
        query="q",
        expected={"answer": "42 ha", "clarification": "TRUE"},
    )
    assert case_to_expected(clarify).expects_data_pull() is False


# ---------------------------------------------------------------------------
# Ground truth: the selector rides the normal prefixing path, the fetched
# values are attached separately, and a case without either is untouched.

GT_CASE = Case(
    id="1-046",
    status="done",
    group="direct",
    query="How many tonnes of CO2 was emitted in Ihorombe, Madagascar in 2019?",
    expected={
        "aoi_ids": "MDG.3.4_1",
        "aoi_source": "gadm",
        "dataset_id": "4",
        "ground_truth": "sum(carbon_emissions_MgCO2e) WHERE tree_cover_loss_year=2019",
        "scope": "analyse",
    },
)


def _ground_truth(values, unresolved=None):
    from goldset.groundtruth import GroundTruth
    from goldset.groundtruth.request import AnalyticsRequest, build_request

    request: AnalyticsRequest = build_request(GT_CASE)
    return GroundTruth(
        uid=GT_CASE.uid,
        case_id=GT_CASE.id,
        selector="sum(x)",
        values=values,
        digest="d",
        request=request,
        resource_id="r",
        unresolved=unresolved,
    )


def test_selector_rides_the_normal_prefixing_path():
    """`ground_truth` is an ordinary expectation, so it needs no special case."""
    expected = case_to_expected(GT_CASE)
    assert expected.expected_ground_truth.startswith("sum(carbon_emissions_MgCO2e)")


def test_fetched_values_are_attached_when_supplied():
    expected = case_to_expected(GT_CASE, _ground_truth([658496.56]))
    assert expected.ground_truth_values == [658496.56]
    assert expected.ground_truth_unresolved == ""


def test_unresolved_selector_rides_along_for_the_scorer():
    """The fetch worked but the metric was absent; the row must ERROR at
    scoring time, so the reason has to reach the evaluators."""
    expected = case_to_expected(GT_CASE, _ground_truth([], unresolved="no such column"))
    assert expected.ground_truth_values == []
    assert expected.ground_truth_unresolved == "no such column"


def test_cases_without_ground_truth_are_built_exactly_as_before():
    """The isolation property. Every non-ground-truth case must produce a
    byte-identical ExpectedData whether or not the mechanism exists, which is
    what lets 90 of the 120 v2 cases be unaffected by this feature.

    Pinned here because `expects_data_pull()` and `implied_checks()` are edited
    in the next phase, and that is the moment this stops being free.
    """
    assert (
        case_to_expected(CASE).model_dump() == case_to_expected(CASE, None).model_dump()
    )
    dumped = case_to_expected(CASE).model_dump()
    assert dumped["ground_truth_values"] == []
    assert dumped["ground_truth_unresolved"] == ""
    assert dumped["expected_ground_truth"] == ""
    # ...and the pre-existing expectations still parse identically.
    assert dumped["expected_aoi_ids"] == ["BRA.25_1", "BRA.14_1"]
    assert dumped["expected_answer"] == "1,319,600 hectares"
