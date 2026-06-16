"""Tests for blog.py cited article extraction from subagent tool calls."""

from unittest.mock import patch

from src.agent.subagents.search.blog import _articles_from_tool_calls

FAKE_INDEX = {
    "some-article": {
        "slug": "some-article",
        "title": "Some Article",
        "abstract": "An abstract.",
        "url": "https://www.wri.org/insights/some-article",
        "lastmod": "2026-01-01T00:00Z",
        "image": "https://files.wri.org/hero.jpg",
        "image_alt": "A hero image",
    },
    "other-article": {
        "slug": "other-article",
        "title": "Other Article",
        "abstract": "Another abstract.",
        "url": "https://www.wri.org/insights/other-article",
        "lastmod": "2026-02-01T00:00Z",
        "image": "",
        "image_alt": "",
    },
}


class _AIMessage:
    def __init__(self, tool_calls):
        self.__class__.__name__ = "AIMessage"
        self.tool_calls = tool_calls


def _patched(messages):
    with patch(
        "src.agent.subagents.search.blog._article_index",
        return_value=FAKE_INDEX,
    ):
        return _articles_from_tool_calls(messages)


def test_extracts_from_article_meta_call():
    msgs = [
        _AIMessage(
            [{"name": "article_meta", "args": {"slugs": ["some-article"]}}]
        )
    ]
    result = _patched(msgs)
    assert len(result) == 1
    assert result[0]["slug"] == "some-article"
    assert result[0]["title"] == "Some Article"
    assert result[0]["image"] == "https://files.wri.org/hero.jpg"


def test_extracts_multiple_from_single_call():
    msgs = [
        _AIMessage(
            [
                {
                    "name": "article_meta",
                    "args": {"slugs": ["some-article", "other-article"]},
                }
            ]
        )
    ]
    result = _patched(msgs)
    assert [r["slug"] for r in result] == ["some-article", "other-article"]


def test_deduplicates_across_multiple_calls():
    msgs = [
        _AIMessage(
            [{"name": "article_meta", "args": {"slugs": ["some-article"]}}]
        ),
        _AIMessage(
            [
                {
                    "name": "article_meta",
                    "args": {"slugs": ["some-article", "other-article"]},
                }
            ]
        ),
    ]
    result = _patched(msgs)
    assert len(result) == 2


def test_ignores_non_article_meta_calls():
    msgs = [
        _AIMessage([{"name": "sgrep", "args": {"query": "peatlands"}}]),
        _AIMessage([{"name": "grep_articles", "args": {"pattern": "peat"}}]),
    ]
    assert _patched(msgs) == []


def test_skips_unknown_slug():
    msgs = [
        _AIMessage(
            [{"name": "article_meta", "args": {"slugs": ["does-not-exist"]}}]
        )
    ]
    assert _patched(msgs) == []


def test_strips_md_extension_from_slug():
    msgs = [
        _AIMessage(
            [{"name": "article_meta", "args": {"slugs": ["some-article.md"]}}]
        )
    ]
    result = _patched(msgs)
    assert len(result) == 1
    assert result[0]["slug"] == "some-article"


def test_returns_empty_for_no_messages():
    assert _patched([]) == []
