"""Unit tests for add_text_widget's pure helpers."""

from src.agent.tools.add_text_widget import _normalize_text, _widget_config


class TestNormalizeText:
    def test_plain_text_passes_through(self):
        assert _normalize_text("A note.") == "A note."

    def test_surrounding_whitespace_stripped(self):
        assert _normalize_text("  A note. \n") == "A note."

    def test_empty_string_is_none(self):
        assert _normalize_text("") is None

    def test_none_is_none(self):
        assert _normalize_text(None) is None

    def test_whitespace_only_is_none(self):
        assert _normalize_text("   \n\t ") is None

    def test_multiline_markdown_preserved(self):
        markdown = "# Title\n\n- one\n- two"
        assert _normalize_text(f"\n{markdown}\n") == markdown


class TestWidgetConfig:
    def test_exact_shape(self):
        # The REST validator (validate_text_config) requires config.text to
        # be a string; the agent path must produce exactly that shape.
        assert _widget_config("# Note") == {"text": "# Note"}
