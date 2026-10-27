"""Tests for tools/audit_cases.py: each audit rule catches the violations it
targets."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from audit_cases import (
    audit,
    depth_violation,
    dont_violations,
    main,
    render,
    selector_violations,
)

from goldset.store import Case

DEEP = Case(
    id="ok-1",
    status="done",
    group="direct",
    query="Loss in Brazil between 2020 and 2022?",
    expected={
        "aoi_ids": "BRA",
        "dataset_id": "4",
        "answer": "2.9 Mha",
        "scope": "analyse",
    },
)


def test_deep_case_is_clean():
    assert depth_violation(DEEP) is None
    assert dont_violations(DEEP) == []


def test_depth_violation_single_bucket():
    shallow = Case(
        id="x",
        status="done",
        group="direct",
        query="q",
        expected={"aoi_ids": "BRA", "dataset_id": "4"},
    )
    # aoi + dataset are both Retrieval: 2 checks, 1 bucket
    assert "1 bucket" in depth_violation(shallow)


def test_metadata_group_is_exempt():
    meta = Case(
        id="m",
        status="done",
        group="metadata",
        query="resolution?",
        expected={"text": "30 x 30 meters"},
    )
    assert depth_violation(meta) is None
    assert dont_violations(meta) == []


def test_relative_dates_flagged_only_with_pinned_expectations():
    pinned = Case(
        id="r1",
        status="done",
        group="direct",
        query="change in the past decade?",
        expected={"answer": "42 ha", "dataset_id": "0", "scope": "analyse"},
    )
    assert any("relative-date" in v for v in dont_violations(pinned))
    routing_only = Case(
        id="r2",
        status="done",
        group="direct",
        query="most recent year of loss data?",
        expected={"dataset_id": "4", "scope": "analyse"},
    )
    assert not any("relative-date" in v for v in dont_violations(routing_only))


def test_relative_date_exempt_only_when_all_keys_are_routing_only():
    # class_values changes as the relative window moves, and it is not in
    # the routing-only allow-list, so the relative-date rule flags it.
    caught = Case(
        id="rc",
        status="done",
        group="class-comparison",
        query="Which land cover class shrank most in the last 5 years?",
        expected={"dataset_id": "7", "scope": "analyse", "class_values": "forest:-120"},
    )
    assert any("relative-date" in v for v in dont_violations(caught))
    # Every key inside ROUTING_ONLY_FIELDS -> still the tolerated pattern.
    exempt = Case(
        id="re",
        status="done",
        group="direct",
        query="Most recent disturbance alerts in Puri district, India?",
        expected={
            "aoi_ids": "IND.26.10_1",
            "aoi_source": "gadm",
            "dataset_id": "11",
            "dataset_name": "DIST alerts",
            "context_layer": "no_selection",
            "scope": "analyse",
            "clarification": "FALSE",
        },
    )
    assert not any("relative-date" in v for v in dont_violations(exempt))


def test_annual_dataset_dates_flagged_alert_datasets_pass():
    annual = Case(
        id="a",
        status="done",
        group="temporal",
        query="q",
        expected={
            "dataset_id": "4",
            "start_date": "2022-01-01",
            "end_date": "2022-12-31",
        },
    )
    assert any("non-date-scoped" in v for v in dont_violations(annual))
    alert = Case(
        id="b",
        status="done",
        group="temporal",
        query="q",
        expected={
            "dataset_id": "11",
            "start_date": "2024-07-01",
            "end_date": "2024-12-31",
        },
    )
    assert dont_violations(alert) == []
    alternatives = Case(
        id="c",
        status="done",
        group="temporal",
        query="q",
        expected={
            "dataset_id": "0;11",
            "start_date": "2025-01-01",
            "end_date": "2025-04-30",
        },
    )
    assert dont_violations(alternatives) == []
    # Mixed alternatives may resolve to the annual dataset: ALL must be
    # date-scoped, not just one of them.
    mixed = Case(
        id="d",
        status="done",
        group="temporal",
        query="q",
        expected={
            "dataset_id": "4;11",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
        },
    )
    assert any("non-date-scoped" in v for v in dont_violations(mixed))


def test_judged_only_answer_in_non_exempt_group_flagged():
    judged = Case(
        id="j",
        status="done",
        group="direct",
        query="How much tree cover did Brazil lose in 2022?",
        expected={"answer": "1.7 Mha"},
    )
    assert dont_violations(judged) == ["j: judged-only expectations"]


def test_multiturn_delta_turns_are_not_judged_only():
    mt = Case(
        id="mt",
        status="ready",
        group="multiturn",
        turns=(
            {"query": "q1", "expected": {"dataset_id": "4", "scope": "analyse"}},
            {
                "query": "are you sure?",
                "expected": {"text": "holds firm"},
                "deltas": {"retain": ["dataset_id"]},
            },
        ),
    )
    assert not any("judged-only" in v for v in dont_violations(mt))


def _gt_case(selector: str) -> Case:
    return Case(
        id="g",
        status="ready",
        group="direct",
        query="CO2 from tree cover loss in Ihorombe, Madagascar in 2019?",
        expected={
            "aoi_ids": "MDG.3.4_1",
            "aoi_source": "gadm",
            "dataset_id": "4",
            "ground_truth": selector,
            "scope": "analyse",
        },
    )


def test_canonically_spelled_selector_is_clean():
    case = _gt_case("sum(carbon_emissions_MgCO2e) WHERE tree_cover_loss_year=2019")
    assert selector_violations(case) == []
    assert dont_violations(case) == [] and depth_violation(case) is None


def test_non_canonical_spelling_is_flagged_with_the_spelling_to_use():
    """The uid hashes the raw string, so `where` and `WHERE` are two versions."""
    problems = selector_violations(
        _gt_case("SUM(area_ha) where tree_cover_loss_year=2019")
    )
    assert len(problems) == 1
    assert "not spelled canonically" in problems[0]
    assert "sum(area_ha) WHERE tree_cover_loss_year=2019" in problems[0]


def test_quoted_values_and_inner_padding_are_flagged_outer_padding_is_not():
    for selector in ("sum(area_ha) WHERE driver='Crop management'", "sum( area_ha )"):
        assert selector_violations(_gt_case(selector)), selector
    # canonical.py strips before hashing, so surrounding whitespace cannot mint
    # a second uid and is not the author's problem to fix.
    assert selector_violations(_gt_case("  sum(area_ha)  ")) == []


def test_unparseable_selector_is_caught_at_audit_not_at_prefetch():
    assert any(
        "cannot parse" in p for p in selector_violations(_gt_case("total of area_ha"))
    )
    assert any(
        "unknown aggregate" in p for p in selector_violations(_gt_case("avg(area_ha)"))
    )


def test_cases_without_a_selector_are_untouched():
    assert selector_violations(DEEP) == []


def test_audit_rollup_and_floors():
    cases = [
        DEEP,
        Case(
            id="p",
            status="not doing",
            group="direct",
            query="parked",
            expected={"aoi_ids": "x"},
        ),
    ]
    report = audit(cases)
    assert report["active"] == 1 and report["parked"] == 1
    assert report["thin_groups"] == {"direct": 1}
    assert report["thin_datasets"] == {"4": 1}
    text = render(report)
    assert "Active cases: 1 (+1 parked)" in text
    assert "- direct: 1" in text


def test_main_cli_reports_by_default_and_fails_under_strict(tmp_path, capsys):
    (tmp_path / "direct").mkdir()
    (tmp_path / "direct" / "fx-1.yaml").write_text(
        "id: fx-1\n"
        "status: done\n"
        "group: direct\n"
        "query: Forest loss in Brazil in the past decade?\n"
        "expected:\n"
        "  answer: 42 ha\n",
        encoding="utf-8",
    )
    assert main(["--cases-dir", str(tmp_path)]) == 0
    report = capsys.readouterr().out
    assert "judged-only" in report
    assert "relative-date" in report
    assert main(["--cases-dir", str(tmp_path), "--strict"]) == 1
