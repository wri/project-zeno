"""Prefetch: resolve ground truth before any trial, and fail loudly."""

import httpx
import pytest

from goldset.groundtruth.client import AnalyticsClient, AnalyticsError
from goldset.groundtruth.fetch import digest, is_ground_truth, prefetch
from goldset.groundtruth.request import RequestError
from goldset.store import Case

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

PLAIN_CASE = Case(
    id="1-002",
    status="done",
    group="direct",
    query="Sao Paulo disturbance?",
    expected={
        "aoi_ids": "BRA.25_1",
        "aoi_source": "gadm",
        "dataset_id": "11",
        "answer": "1,299,278 hectares",
        "scope": "analyse",
    },
)

RESULT = {
    "aoi_id": ["MDG.3.4", "MDG.3.4"],
    "tree_cover_loss_year": [2018, 2019],
    "area_ha": [1000.0, 1371.15],
    "carbon_emissions_MgCO2e": [500000.0, 658496.56],
}


def _client(handler) -> AnalyticsClient:
    return AnalyticsClient(token="t", transport=httpx.MockTransport(handler))


def _ok(result=RESULT, metadata=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200, json={"status": "saved", "data": {"link": "http://a/x/res-1"}}
            )
        return httpx.Response(
            200,
            json={"data": {"result": result, "metadata": metadata or {"echo": True}}},
        )

    return handler


def test_resolves_a_ground_truth_case():
    got = prefetch([GT_CASE], _client(_ok()))
    assert list(got) == [GT_CASE.uid]
    gt = got[GT_CASE.uid]
    assert gt.values == pytest.approx([658496.56])
    assert gt.case_id == "1-046"
    assert gt.resource_id == "res-1"
    assert gt.metadata == {"echo": True}
    assert gt.unresolved is None
    assert gt.request.payload["aoi"] == {"type": "admin", "ids": ["MDG.3.4"]}


def test_cases_without_ground_truth_are_skipped_entirely():
    """The mechanism must be invisible to the other 90 cases."""
    assert is_ground_truth(GT_CASE) and not is_ground_truth(PLAIN_CASE)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("a non-ground-truth case must not be fetched")

    assert prefetch([PLAIN_CASE], _client(handler)) == {}


def test_fetch_failure_raises_so_the_run_can_abort():
    """A failed fetch aborts before any trial."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "failed", "message": "boom"})

    with pytest.raises(AnalyticsError, match="job failed"):
        prefetch([GT_CASE], _client(handler))


def test_empty_result_raises():
    """'returns nothing' is a failure, not an empty expectation."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200, json={"status": "saved", "data": {"link": "http://a/x/1"}}
            )
        return httpx.Response(200, json={"data": {"result": {}}})

    with pytest.raises(AnalyticsError, match="empty result"):
        prefetch([GT_CASE], _client(handler))


def test_unbuildable_case_raises():
    """A case whose request cannot be built aborts rather than guessing."""
    broken = Case(
        id="x",
        status="done",
        group="direct",
        query="q",
        expected={"aoi_ids": "RUS", "dataset_id": "4", "ground_truth": "sum(area_ha)"},
    )  # no aoi_source
    with pytest.raises(RequestError, match="no aoi_source"):
        prefetch([broken], _client(_ok()))


def test_missing_metric_is_recorded_not_raised():
    case = Case(
        id="y",
        status="done",
        group="direct",
        query="q",
        expected={
            "aoi_ids": "MDG.3.4_1",
            "aoi_source": "gadm",
            "dataset_id": "4",
            "ground_truth": "sum(no_such_column)",
        },
    )
    got = prefetch([case], _client(_ok()))
    gt = got[case.uid]
    assert gt.unresolved is not None
    assert "not in the response" in gt.unresolved
    assert gt.values == []


NULL_EMISSIONS = {
    "aoi_id": ["FIN", "FIN"],
    "aoi_type": ["admin", "admin"],
    "tree_cover_loss_year": [2024, 2025],
    "area_ha": [198000.0, 241368.24],
    "carbon_emissions_MgCO2e": None,
}


def _finland(selector: str) -> Case:
    return Case(
        id="1-095",
        status="done",
        group="dataset-parameters",
        query="q",
        expected={
            "aoi_ids": "FIN",
            "aoi_source": "gadm",
            "dataset_id": "4",
            "dataset_parameters": '[{"name": "canopy_cover", "values": [10]}]',
            "ground_truth": selector,
        },
    )


def test_a_null_column_does_not_abort_the_run():
    case = _finland("sum(area_ha) WHERE tree_cover_loss_year=2025")
    gt = prefetch([case], _client(_ok(result=NULL_EMISSIONS)))[case.uid]
    assert gt.values == pytest.approx([241368.24])
    assert gt.unresolved is None


def test_selecting_the_null_column_is_a_row_error_not_an_abort():
    """Asking for emissions at canopy 10 asks for a metric the API did not
    compute: the same absence as a missing column, so the same row error."""
    case = _finland("sum(carbon_emissions_MgCO2e) WHERE tree_cover_loss_year=2025")
    gt = prefetch([case], _client(_ok(result=NULL_EMISSIONS)))[case.uid]
    assert gt.values == []
    assert "did not compute it" in gt.unresolved


def test_digest_moves_with_the_values_and_only_with_them():
    assert digest([658496.56]) == digest([658496.56])
    assert digest([658496.56]) != digest([658500.0])
    # order-independent, so a reordered multi-value response is not a bump
    assert digest([1.0, 2.0]) == digest([2.0, 1.0])


def test_selected_values_not_the_whole_table_are_hashed():
    before = prefetch([GT_CASE], _client(_ok()))[GT_CASE.uid]
    extended = {
        **RESULT,
        "aoi_id": [*RESULT["aoi_id"], "MDG.3.4"],
        "tree_cover_loss_year": [*RESULT["tree_cover_loss_year"], 2026],
        "area_ha": [*RESULT["area_ha"], 2000.0],
        "carbon_emissions_MgCO2e": [*RESULT["carbon_emissions_MgCO2e"], 900000.0],
    }
    after = prefetch([GT_CASE], _client(_ok(extended)))[GT_CASE.uid]
    assert before.digest == after.digest

    # ...whereas a case summing every year does move.
    total = Case(
        id="1-076",
        status="done",
        group="direct",
        query="q",
        expected={
            "aoi_ids": "RUS",
            "aoi_source": "gadm",
            "dataset_id": "4",
            "ground_truth": "sum(area_ha)",
        },
    )
    a = prefetch([total], _client(_ok()))[total.uid]
    b = prefetch([total], _client(_ok(extended)))[total.uid]
    assert a.digest != b.digest


def test_ledger_block_carries_what_an_audit_needs():
    """Request, values, digest, resource id, and the server's echo."""
    gt = prefetch([GT_CASE], _client(_ok(metadata={"aoi": {"version": "4.1"}})))
    record = gt[GT_CASE.uid].to_ledger()
    assert set(record) >= {
        "selector",
        "values",
        "digest",
        "resource_id",
        "fetched_at",
        "request",
        "metadata",
    }
    assert record["request"]["endpoint"].endswith("/tree_cover_loss/analytics")
    assert record["metadata"] == {"aoi": {"version": "4.1"}}
    # 4, 8 and 10 share that endpoint, so the dataset is recorded explicitly
    assert record["dataset_id"] == "4"
    assert record["content_date_fixed"] is False
    assert "unresolved" not in record


def test_unresolved_ledger_block_carries_no_digest():
    """digest([]) is one constant for every unresolved case: recording it would
    let two failing runs read as 'same data'."""
    case = Case(
        id="y",
        status="done",
        group="direct",
        query="q",
        expected={
            "aoi_ids": "MDG.3.4_1",
            "aoi_source": "gadm",
            "dataset_id": "4",
            "ground_truth": "sum(no_such_column)",
        },
    )
    record = prefetch([case], _client(_ok()))[case.uid].to_ledger()
    assert "digest" not in record
    assert "not in the response" in record["unresolved"]


def test_unparseable_selector_aborts_the_run_cleanly(capsys):
    """A selector with no aggregate must reach the ABORT line, not a
    traceback. Parsing happens before any request, so no transport is needed."""
    import argparse

    from goldset.cli import prefetch_ground_truth
    from goldset.groundtruth.client import BASE_URL

    case = Case(
        id="z",
        status="done",
        group="direct",
        query="q",
        expected={
            "aoi_ids": "RUS",
            "aoi_source": "gadm",
            "dataset_id": "4",
            "ground_truth": "area_ha",
        },
    )
    args = argparse.Namespace(api_token="t", verbose=False)
    assert prefetch_ground_truth(args, [case]) is False
    assert "ABORT" in capsys.readouterr().out
    assert args.analytics_base_url == BASE_URL


def test_analytics_header_is_always_production():
    from goldset.groundtruth.client import analytics_headers

    assert analytics_headers("t")["X-environment"] == "production"
