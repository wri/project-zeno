"""Inspector rendering: injection, escaping, case-context join."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from render_inspector import PLACEHOLDER, TEMPLATE, render_inspector

RUN = {
    "run_id": "20260802T000000Z_staging",
    "started": "2026-08-02T00:00:00Z",
    "environment": "staging",
    "build": "b",
    "ff": None,
    "harness": {"repo": "gnw-gold-evals", "sha": "x"},
    "judge_model": "claude-haiku-4-5",
    "num_trials": 3,
    "caseset_version": "abc",
    "results": [
        {
            "uid": "u1",
            "id": "1-001",
            "checks": {"aoi_id_match": 1.0, "agent_answer": 0.0},
            "reasons": {"agent_answer": "wrong number </script> injection"},
            "actuals": {"agent_answer": "2,000 ha"},
            "trials": [
                {"checks": {"aoi_id_match": 1.0, "agent_answer": 0.0}},
                {"checks": {"aoi_id_match": 1.0, "agent_answer": 1.0}},
                {"checks": {"aoi_id_match": 1.0, "agent_answer": 0.0}},
            ],
        }
    ],
}


def test_injection_and_escaping():
    text = render_inspector(
        RUN,
        TEMPLATE.read_text(encoding="utf-8"),
        "now",
        cases={
            "u1": {"query": "q?", "group": "direct", "expected": {"answer": "1,000 ha"}}
        },
    )
    assert PLACEHOLDER not in text
    assert "20260802T000000Z_staging" in text
    # </script> inside the payload must not terminate the inline script
    assert "</script> injection" not in text
    assert "<\\/script> injection" in text


def test_template_missing_placeholder_refused():
    with pytest.raises(ValueError, match="placeholder"):
        render_inspector(RUN, "<html></html>", "now")


def test_template_standalone_supports_drag_drop():
    text = TEMPLATE.read_text(encoding="utf-8")
    assert 'addEventListener("drop"' in text
    assert "flakySet" in text  # trials-disagree tagging is present


def test_all_runs_injection_embeds_every_run():
    from render_inspector import render_inspector_all

    second = {
        **RUN,
        "run_id": "20260803T000000Z_staging",
        "started": "2026-08-03T00:00:00Z",
    }
    text = render_inspector_all(
        [second, RUN], TEMPLATE.read_text(encoding="utf-8"), "now"
    )
    payload = text.split('type="application/json">')[1].split("</script>")[0]
    assert '"runs"' in payload
    assert "20260802T000000Z_staging" in payload
    assert "20260803T000000Z_staging" in payload


def test_template_has_run_picker():
    text = TEMPLATE.read_text(encoding="utf-8")
    assert 'id="runsel"' in text  # dropdown exists
    assert "toLocaleString" in text  # human-readable datetime labels
