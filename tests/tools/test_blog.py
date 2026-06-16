"""Tests for blog.py cited article extraction and search_blogs tool."""

from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage
from langgraph.types import Command

from src.agent.subagents.search.blog import (
    _articles_from_tool_calls,
    _paragraph_index,
    grep_articles,
    search_blogs,
)

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


# --- search_blogs tool ---


def _make_subagent_result(answer: str, article_slugs: list[str]) -> dict:
    """Build a minimal fake subagent message trace."""
    tool_call_msg = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "article_meta",
                "args": {"slugs": article_slugs},
                "id": "call_1",
                "type": "tool_call",
            }
        ],
    )
    answer_msg = AIMessage(content=answer)
    return {"messages": [tool_call_msg, answer_msg]}


@pytest.mark.asyncio
async def test_search_blogs_returns_command_with_answer_and_cited_articles():
    fake_result = _make_subagent_result(
        "Peatlands cover 12% of land.", ["some-article"]
    )
    mock_agent = AsyncMock()
    mock_agent.ainvoke.return_value = fake_result

    with (
        patch(
            "src.agent.subagents.search.blog._cached_agent",
            return_value=mock_agent,
        ),
        patch(
            "src.agent.subagents.search.blog._article_index",
            return_value=FAKE_INDEX,
        ),
    ):
        cmd = await search_blogs.ainvoke(
            {
                "type": "tool_call",
                "name": "search_blogs",
                "args": {"query": "peatlands"},
                "id": "tc-1",
            }
        )

    assert isinstance(cmd, Command)
    tool_msg = cmd.update["messages"][0]
    assert tool_msg.content == "Peatlands cover 12% of land."
    assert tool_msg.tool_call_id == "tc-1"
    assert len(cmd.update["cited_articles"]) == 1
    assert cmd.update["cited_articles"][0]["slug"] == "some-article"


@pytest.mark.asyncio
async def test_search_blogs_returns_fallback_when_no_answer():
    mock_agent = AsyncMock()
    mock_agent.ainvoke.return_value = {"messages": []}

    with patch(
        "src.agent.subagents.search.blog._cached_agent",
        return_value=mock_agent,
    ):
        cmd = await search_blogs.ainvoke(
            {
                "type": "tool_call",
                "name": "search_blogs",
                "args": {"query": "peatlands"},
                "id": "tc-2",
            }
        )

    assert isinstance(cmd, Command)
    assert "No answer" in cmd.update["messages"][0].content
    assert cmd.update["cited_articles"] == []


# --- grep_articles (in-memory index) ---

FAKE_PARAGRAPHS = [
    ("article-a.md", 1, "Indonesia peatlands cover 12 percent of land."),
    ("article-a.md", 2, "Peat fires release large amounts of CO2."),
    ("article-b.md", 1, "Forest Resilience Bond raised 4.6 million dollars."),
    ("article-b.md", 3, "The Yuba watershed covers 15000 acres."),
    ("article-c.md", 1, "WRI works on climate adaptation globally."),
]


def _patched_grep(pattern, slugs=None, max_results=10):
    _paragraph_index.cache_clear()
    with patch(
        "src.agent.subagents.search.blog._paragraph_index",
        return_value=FAKE_PARAGRAPHS,
    ):
        return grep_articles.invoke(
            {"pattern": pattern, "slugs": slugs, "max_results": max_results}
        )


def test_grep_articles_finds_match_in_memory():
    result = _patched_grep("peat")
    assert "article-a.md" in result
    assert "§1" in result or "§2" in result


def test_grep_articles_slug_filter_restricts_to_specified_articles():
    result = _patched_grep("peat", slugs=["article-b"])
    assert "No matches found" in result


def test_grep_articles_slug_filter_finds_match_in_scoped_articles():
    result = _patched_grep("Yuba", slugs=["article-b"])
    assert "article-b.md" in result
    assert "article-a.md" not in result


def test_grep_articles_slug_filter_accepts_md_extension():
    result = _patched_grep("Yuba", slugs=["article-b.md"])
    assert "article-b.md" in result


def test_grep_articles_respects_max_results():
    result = _patched_grep("a", max_results=2)
    assert result.count("\n") < 2  # at most 2 lines
