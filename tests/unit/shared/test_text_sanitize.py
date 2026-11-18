"""Unit tests for stripping control characters from model output (PZB-1243).

Built up one test at a time, ordered by the transformation priority premise.
"""

from src.shared.text_sanitize import strip_control_chars


def test_accented_text_passes_through_unchanged():
    assert strip_control_chars("Paraná") == "Paraná"


def test_nul_is_removed():
    assert strip_control_chars("Piau\x00") == "Piau"


def test_other_control_characters_are_removed():
    assert strip_control_chars("Maranh\x03o") == "Maranho"


def test_tab_newline_and_carriage_return_survive():
    assert strip_control_chars("a\tb\nc\r\n") == "a\tb\nc\r\n"


def test_del_is_removed():
    assert strip_control_chars("Guam\x7f") == "Guam"


def test_replacement_character_is_removed():
    assert strip_control_chars("Guam\ufffd") == "Guam"
