"""HTML report generator (skeleton + injection)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from render_html import PLACEHOLDER, TEMPLATE, render_report

RUN = {
    "run_id": "20260801T000000Z_staging",
    "started": "2026-08-01T00:00:00Z",
    "environment": "staging",
    "build": "GNW test",
    "ff": None,
    "harness": {"repo": "x", "sha": "y"},
    "judge_model": "claude-haiku-4-5",
    "num_trials": 3,
    "caseset_version": "cs1",
    "buckets": {
        "retrieval": {
            "dedicated": {"passed": 9, "evaluated": 10},
            "shared": {"passed": 0, "evaluated": 0},
            "rows_covered": 8,
        },
        "analysis": {
            "dedicated": {"passed": 0, "evaluated": 0},
            "shared": {"passed": 3, "evaluated": 4},
            "rows_covered": 4,
        },
        "explanation": {
            "dedicated": {"passed": 0, "evaluated": 0},
            "shared": {"passed": 0, "evaluated": 0},
            "rows_covered": 0,
        },
        "output": {
            "dedicated": {"passed": 1, "evaluated": 2},
            "shared": {"passed": 0, "evaluated": 0},
            "rows_covered": 2,
        },
        "scope": {
            "dedicated": {"passed": 0, "evaluated": 0},
            "shared": {"passed": 0, "evaluated": 0},
            "rows_covered": 0,
        },
        "rows_total": 8,
        "verdicts": {"pass": 6, "fail": 1, "error": 1, "uncovered": 0},
    },
    "results": [
        {
            "uid": "u1",
            "id": "1-001",
            "checks": {"aoi_id_match": 1.0},
            "latency_s": 40.0,
        },
        {
            "uid": "u2",
            "id": "1-002",
            "checks": {"aoi_id_match": 0.0, "agent_answer": 0.0},
            "reasons": {"agent_answer": 'figure off by <12%> & "quoted"'},
            "trace_url": "https://lf/t2",
            "latency_s": 50.0,
        },
        {
            "uid": "u3",
            "id": "1-003",
            "checks": {"aoi_id_match": 1.0},
            "judge_errors": ["agent_answer"],
        },
    ],
}


def test_template_has_placeholder_and_drop_zone():
    text = TEMPLATE.read_text(encoding="utf-8")
    assert PLACEHOLDER in text
    assert "Drop a" in text  # standalone (uninjected) mode exists


def test_injection_produces_selfcontained_report():
    contexts = {
        "u2": {
            "query": "Sao Paulo disturbance in H2 2024?",
            "group": "direct",
            "scope": "analyse",
            "expected": {"aoi_ids": "BRA.25_1", "answer": "1,319,600 ha"},
        }
    }
    html = render_report(
        RUN, TEMPLATE.read_text(encoding="utf-8"), "test-time", cases=contexts
    )
    assert PLACEHOLDER not in html
    assert '"run_id": "20260801T000000Z_staging"'.replace(" ", "") in html.replace(
        " ", ""
    )
    assert '"info_only"' in html
    assert "Sao Paulo disturbance" in html  # prompt context rides along
    # reason text with </ must not terminate the inline script
    assert "</" not in html.split('type="application/json">')[1].split("</script>")[0]


def test_case_context_extraction(tmp_path):
    from render_html import load_case_contexts

    from goldset.store import Case, write_case

    case = Case(
        id="1-002",
        status="done",
        group="direct",
        query="Sao Paulo disturbance in H2 2024?",
        expected={"aoi_ids": "BRA.25_1", "scope": "analyse"},
    )
    write_case(tmp_path, case)
    contexts = load_case_contexts(
        tmp_path,
        {
            "results": [
                {"uid": case.uid, "id": "1-002", "checks": {}},
                {"uid": "absent-uid-1234567", "id": "9-999", "checks": {}},
            ]
        },
    )
    assert contexts[case.uid]["query"].startswith("Sao Paulo")
    assert contexts[case.uid]["scope"] == "analyse"
    assert contexts[case.uid]["status"] == "done"
    assert "absent-uid-1234567" not in contexts  # unresolvable: omitted, not faked


def test_injection_requires_placeholder():
    with pytest.raises(ValueError, match="placeholder"):
        render_report(RUN, "<html>no slot</html>", "t")


def test_all_runs_injection_embeds_every_run():
    from render_html import render_report_all

    second = {
        **RUN,
        "run_id": "20260802T000000Z_staging",
        "started": "2026-08-02T00:00:00Z",
    }
    html = render_report_all([second, RUN], TEMPLATE.read_text(encoding="utf-8"), "t")
    payload = html.split('type="application/json">')[1].split("</script>")[0]
    assert '"runs"' in payload and '"run":' not in payload
    assert "20260801T000000Z_staging" in payload
    assert "20260802T000000Z_staging" in payload


def test_template_has_run_picker():
    text = TEMPLATE.read_text(encoding="utf-8")
    assert 'id="runsel"' in text  # dropdown exists
    assert "toLocaleString" in text  # human-readable datetime labels


def test_load_all_runs_rejects_empty_dir(tmp_path):
    from render_html import load_all_runs

    with pytest.raises(FileNotFoundError, match="no run JSONs"):
        load_all_runs(tmp_path)
