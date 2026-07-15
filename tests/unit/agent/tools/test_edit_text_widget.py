"""Unit tests for edit_text_widget's pure helpers."""

from types import SimpleNamespace
from uuid import uuid4

from src.agent.tools.edit_text_widget import _excerpt, _select_text_widget


def _widget(widget_type="text", text="A note."):
    config = {"text": text} if widget_type == "text" else {}
    return SimpleNamespace(id=uuid4(), widget_type=widget_type, config=config)


class TestSelectTextWidget:
    def test_empty_list_is_error(self):
        widget, message = _select_text_widget([])
        assert widget is None
        assert "No text widget" in message

    def test_only_non_text_widgets_is_error(self):
        widgets = [_widget("insight"), _widget("map")]
        widget, message = _select_text_widget(widgets)
        assert widget is None
        assert "No text widget" in message

    def test_single_text_widget_returned(self):
        only = _widget()
        widget, message = _select_text_widget([only])
        assert widget is only
        assert message is None

    def test_multiple_text_widgets_lists_all_candidates(self):
        first = _widget(text="First note.")
        second = _widget(text="Second note.")
        widget, message = _select_text_widget([first, second])
        assert widget is None
        assert "pass widget_id" in message
        for candidate in (first, second):
            assert str(candidate.id) in message
            assert candidate.config["text"] in message

    def test_mixed_list_picks_the_text_widget(self):
        note = _widget()
        widgets = [_widget("insight"), note, _widget("map")]
        widget, message = _select_text_widget(widgets)
        assert widget is note
        assert message is None

    def test_text_widget_without_config_still_selectable(self):
        # Defensive: a text widget whose config lost its body should still
        # be the edit target (the edit replaces the body anyway).
        bare = SimpleNamespace(id=uuid4(), widget_type="text", config=None)
        widget, message = _select_text_widget([bare])
        assert widget is bare
        assert message is None


class TestExcerpt:
    def test_short_text_unchanged(self):
        assert _excerpt("A short note.") == "A short note."

    def test_long_text_truncated_with_ellipsis(self):
        long_text = "x" * 100
        result = _excerpt(long_text, max_chars=60)
        assert result == "x" * 60 + "…"

    def test_exact_limit_not_truncated(self):
        text = "x" * 60
        assert _excerpt(text, max_chars=60) == text

    def test_whitespace_stripped_before_truncation(self):
        assert _excerpt("  padded  ") == "padded"

    def test_empty_and_none_are_empty(self):
        assert _excerpt("") == ""
        assert _excerpt(None) == ""
