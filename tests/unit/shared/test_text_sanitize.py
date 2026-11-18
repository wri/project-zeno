"""Unit tests for stripping control characters from model output (PZB-1243).

Built up one test at a time, ordered by the transformation priority premise.
"""

import pytest

from src.shared import text_sanitize
from src.shared.text_sanitize import strip_control_chars


class _RecordingLogger:
    """Collect each warning as (event, fields). Every other call does nothing.

    The module logger is swapped rather than using
    ``structlog.testing.capture_logs``, because ``cache_logger_on_first_use``
    binds the logger on its first call and capture then misses the record
    (see tests/api/test_aoi_lookup.py).
    """

    def __init__(self):
        self.warnings = []

    def warning(self, event, **fields):
        self.warnings.append((event, fields))

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


@pytest.fixture
def warnings(monkeypatch):
    recorder = _RecordingLogger()
    monkeypatch.setattr(text_sanitize, "logger", recorder)
    return recorder.warnings


def test_accented_text_passes_through_unchanged():
    assert strip_control_chars("Paraná", field="insight_text") == "Paraná"


def test_nul_is_removed():
    assert strip_control_chars("Piau\x00", field="insight_text") == "Piau"


def test_other_control_characters_are_removed():
    assert (
        strip_control_chars("Maranh\x03o", field="insight_text") == "Maranho"
    )


def test_tab_newline_and_carriage_return_survive():
    assert (
        strip_control_chars("a\tb\nc\r\n", field="insight_text")
        == "a\tb\nc\r\n"
    )


def test_del_is_removed():
    assert strip_control_chars("Guam\x7f", field="insight_text") == "Guam"


def test_replacement_character_is_removed():
    assert strip_control_chars("Guam�", field="insight_text") == "Guam"


def test_stripping_logs_one_warning_with_field_and_count(warnings):
    strip_control_chars("Piau\x00 and Maranh\x03o", field="insight_text")

    ((event, fields),) = warnings
    assert event == "control_chars_stripped"
    assert fields["field"] == "insight_text"
    assert fields["count"] == 2


def test_warning_lists_removed_codepoints(warnings):
    strip_control_chars("Piau\x00 and Maranh\x03o", field="insight_text")

    ((_, fields),) = warnings
    assert fields["codepoints"] == ["U+0000", "U+0003"]


def test_clean_text_logs_nothing(warnings):
    strip_control_chars("Paraná\tMaranhão\n", field="insight_text")

    assert warnings == []


def test_snippet_shows_removed_characters_escaped(warnings):
    strip_control_chars("Paraná and Maranh\x03o", field="insight_text")

    ((_, fields),) = warnings
    assert fields["snippet"] == "Paraná and Maranh\\x03o"


def test_snippet_is_a_window_around_the_first_removed_character(warnings):
    strip_control_chars("a" * 30 + "\x00" + "b" * 30, field="insight_text")

    ((_, fields),) = warnings
    assert fields["snippet"] == "a" * 20 + "\\x00" + "b" * 20


def test_repeated_codepoint_is_listed_once_but_counted_each_time(warnings):
    strip_control_chars("Piau\x00 and Piau\x00", field="insight_text")

    ((_, fields),) = warnings
    assert fields["codepoints"] == ["U+0000"]
    assert fields["count"] == 2
