"""Tests for goldset.templates: query template variable resolution."""

from datetime import datetime

import pytest

from goldset.templates import (
    TEMPLATE_VARS,
    has_templates,
    resolve_templates,
    validate_templates,
)

FIXED_NOW = datetime(2026, 8, 15, 10, 0, 0)


class TestResolveTemplates:
    def test_current_month(self):
        assert resolve_templates("{current_month}", now=FIXED_NOW) == "August 2026"

    def test_last_month(self):
        assert resolve_templates("{last_month}", now=FIXED_NOW) == "July 2026"

    def test_last_month_january_wraps(self):
        jan = datetime(2026, 1, 10)
        assert resolve_templates("{last_month}", now=jan) == "December 2025"

    def test_current_year(self):
        assert resolve_templates("{current_year}", now=FIXED_NOW) == "2026"

    def test_no_tokens(self):
        plain = "Show me alerts for Brazil."
        assert resolve_templates(plain, now=FIXED_NOW) == plain

    def test_multiple_tokens(self):
        text = "From {last_month} to {current_month}"
        assert resolve_templates(text, now=FIXED_NOW) == "From July 2026 to August 2026"

    def test_embedded_in_sentence(self):
        text = "Show me imagery from {current_month} for Zurich."
        assert resolve_templates(text, now=FIXED_NOW) == (
            "Show me imagery from August 2026 for Zurich."
        )

    def test_unknown_token_raises(self):
        with pytest.raises(KeyError, match="bogus"):
            resolve_templates("{bogus}", now=FIXED_NOW)


class TestValidateTemplates:
    def test_valid_tokens(self):
        for name in TEMPLATE_VARS:
            assert validate_templates(f"{{{name}}}") == []

    def test_unknown_token(self):
        problems = validate_templates("imagery from {next_year}")
        assert len(problems) == 1
        assert "next_year" in problems[0]

    def test_no_tokens(self):
        assert validate_templates("plain text") == []

    def test_multiple_unknown(self):
        problems = validate_templates("{foo} and {bar}")
        assert len(problems) == 2


class TestHasTemplates:
    def test_with_template(self):
        assert has_templates("from {current_month}") is True

    def test_without_template(self):
        assert has_templates("plain query") is False

    def test_curly_braces_non_token(self):
        assert has_templates("JSON {Key: value}") is False
