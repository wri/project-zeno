"""Unit tests for stripping control characters from LLM-written text."""

import pytest
import structlog.testing

from src.shared.text_sanitize import clean_json, strip_control_chars


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Piau\x00", "Piau"),
        ("Par\x00\x00", "Par"),
        ("Maranh\x03o", "Maranho"),
        ("a\x7fb", "ab"),
        ("\x00\x01\x1f", ""),
    ],
)
def test_strips_control_characters(raw, expected):
    assert strip_control_chars(raw) == expected


def test_keeps_whitespace_and_real_text():
    text = "Piauí\tlost 3,600 ha.\nMaranhão — 12%\r\n“quoted” 中国"
    assert strip_control_chars(text) == text


def test_clean_json_walks_nested_structures():
    value = {
        "ti\x00tle": "Piau\x00",
        "rows": [{"place": "Maranh\x03o", "loss": 5}, ("a\x00", 1.5, None)],
        "ok": True,
    }
    assert clean_json(value) == {
        "title": "Piau",
        "rows": [{"place": "Maranho", "loss": 5}, ["a", 1.5, None]],
        "ok": True,
    }


# --- warning log when something is stripped -------------------------------


def _stripped(logs):
    return [log for log in logs if log["event"] == "control_chars_stripped"]


def test_strip_logs_a_warning_with_field_codepoints_and_context():
    with structlog.testing.capture_logs() as logs:
        result = strip_control_chars(
            "In Maranh\x03o, loss rose.\x00", field="insight_text"
        )

    assert result == "In Maranho, loss rose."
    (entry,) = _stripped(logs)
    assert entry["log_level"] == "warning"
    assert entry["field"] == "insight_text"
    assert entry["count"] == 2
    assert entry["codepoints"] == ["U+0000", "U+0003"]
    assert "Maranh" in entry["context"]
    assert len(entry["context"]) <= 40


def test_strip_does_not_log_when_nothing_is_removed():
    with structlog.testing.capture_logs() as logs:
        strip_control_chars("Piauí\tlost 3,600 ha.\n", field="insight_text")
        clean_json({"title": "Maranhão", "rows": [1, 2]}, field="chart_row")

    assert _stripped(logs) == []


def test_clean_json_logs_once_for_the_whole_structure():
    value = {"ti\x00tle": "Piau\x00", "rows": [{"place": "Maranh\x03o"}]}

    with structlog.testing.capture_logs() as logs:
        clean_json(value, field="chart_row")

    (entry,) = _stripped(logs)
    assert entry["field"] == "chart_row"
    assert entry["count"] == 3
    assert entry["codepoints"] == ["U+0000", "U+0003"]
