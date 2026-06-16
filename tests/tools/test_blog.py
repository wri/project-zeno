"""Tests for blog.py citation extraction."""

from unittest.mock import patch

from src.agent.subagents.search.blog import _extract_cited_articles

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


def _patched(answer: str) -> list[dict]:
    with patch(
        "src.agent.subagents.search.blog._article_index",
        return_value=FAKE_INDEX,
    ):
        return _extract_cited_articles(answer)


def test_extracts_single_citation():
    answer = (
        "Forests are shrinking [1](https://www.wri.org/insights/some-article)."
    )
    result = _patched(answer)
    assert len(result) == 1
    assert result[0]["slug"] == "some-article"
    assert result[0]["title"] == "Some Article"
    assert result[0]["image"] == "https://files.wri.org/hero.jpg"


def test_extracts_multiple_citations():
    answer = (
        "First point [1](https://www.wri.org/insights/some-article). "
        "Second point [2](https://www.wri.org/insights/other-article)."
    )
    result = _patched(answer)
    assert [r["slug"] for r in result] == ["some-article", "other-article"]


def test_deduplicates_repeated_citation():
    answer = (
        "First [1](https://www.wri.org/insights/some-article). "
        "Again [1](https://www.wri.org/insights/some-article)."
    )
    result = _patched(answer)
    assert len(result) == 1


def test_returns_empty_for_no_citations():
    assert _patched("No citations here.") == []


def test_skips_unknown_slug():
    answer = "Unknown [1](https://www.wri.org/insights/does-not-exist)."
    assert _patched(answer) == []


def test_strips_fragment_from_url():
    answer = "Cited [1](https://www.wri.org/insights/some-article#p3)."
    result = _patched(answer)
    assert len(result) == 1
    assert result[0]["slug"] == "some-article"
