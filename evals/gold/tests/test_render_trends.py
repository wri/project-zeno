"""Trends page rendering: injection, escaping, template affordances."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from render_trends import PLACEHOLDER, TEMPLATE, render_trends

RUN = {
    "run_id": "20260801T000000Z_staging_experimental",
    "started": "2026-08-01T00:00:00Z",
    "environment": "staging",
    "build": "b </script>",
    "ff": "experimental",
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
        "rows_total": 8,
        "verdicts": {"pass": 6, "fail": 1, "error": 1, "uncovered": 0},
    },
    "results": [
        {"uid": "u1", "id": "1-001", "checks": {"aoi_id_match": 1.0}, "latency_s": 40.0}
    ],
}


def test_injection_embeds_runs_and_escapes():
    second = {
        **RUN,
        "run_id": "20260802T000000Z_staging",
        "started": "2026-08-02T00:00:00Z",
        "ff": None,
    }
    html = render_trends([second, RUN], TEMPLATE.read_text(), "now")
    assert PLACEHOLDER not in html
    payload = html.split('type="application/json">')[1].split("</script>")[0]
    assert '"runs"' in payload
    assert "20260801T000000Z_staging_experimental" in payload
    assert "20260802T000000Z_staging" in payload
    # </script> inside a build label must not terminate the inline script
    assert "</" not in payload


def test_template_missing_placeholder_refused():
    with pytest.raises(ValueError, match="placeholder"):
        render_trends([RUN], "<html></html>", "now")


def test_template_affordances():
    text = TEMPLATE.read_text()
    assert PLACEHOLDER in text
    assert 'addEventListener("drop"' in text  # standalone drag-drop mode
    assert 'id="f-ff"' in text  # ff filter: never trend across ff
    assert "caseset" in text  # caseset changes are surfaced
    assert "Table view" in text  # no-hover data channel
