import src.agent.tools.wri_insights_store as store
from src.agent.tools.wri_insights_store import (
    _parse_meta,
    _pending_jobs,
    linkify_citations,
)

SAMPLE = """\
# Example Article

**URL:** https://www.wri.org/insights/example-article
**Last modified:** 2026-05-05T21:01Z

> Abstract text.
[§1] First paragraph.

[§2 | Section: "Background"] Second paragraph.
"""


def test_linkify_citations_makes_paragraph_tags_clickable() -> None:
    out = linkify_citations(SAMPLE)
    assert "[§1](https://www.wri.org/insights/example-article#p1)" in out
    assert (
        '[§2 | Section: "Background"]'
        "(https://www.wri.org/insights/example-article#p2)"
    ) in out
    assert "**URL:** [https://www.wri.org/insights/example-article]" in out


def test_linkify_citations_is_idempotent() -> None:
    once = linkify_citations(SAMPLE)
    assert linkify_citations(once) == once


META_HTML = """\
<html><head>
<meta name="citation_title" content="Test Article" />
<meta name="description" content="An abstract." />
<meta property="og:image" content="https://files.wri.org/hero.jpg" />
<meta property="og:image:alt" content="A hero image" />
</head><body></body></html>
"""


def test_parse_meta_extracts_og_image() -> None:
    assert _parse_meta(META_HTML) == {
        "title": "Test Article",
        "abstract": "An abstract.",
        "image": "https://files.wri.org/hero.jpg",
        "image_alt": "A hero image",
    }


def test_parse_meta_defaults_to_empty_strings() -> None:
    assert _parse_meta("<html></html>") == {
        "title": "",
        "abstract": "",
        "image": "",
        "image_alt": "",
    }


def test_pending_jobs_backfills_entries_without_image_key(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(store, "_DATA_DIR", tmp_path)
    (tmp_path / "old.md").write_text("x")
    (tmp_path / "new.md").write_text("x")
    urls = [
        ("https://www.wri.org/insights/old", "2026-01-01"),
        ("https://www.wri.org/insights/new", "2026-01-01"),
    ]
    existing = {
        # predates og:image capture (no "image" key) -> refetched once
        "old": {"slug": "old", "lastmod": "2026-01-01"},
        # already backfilled; empty image means the page has no og:image
        "new": {"slug": "new", "lastmod": "2026-01-01", "image": ""},
    }

    pending, skipped = _pending_jobs(urls, force=False, existing=existing)

    assert [url for url, _ in pending] == ["https://www.wri.org/insights/old"]
    assert skipped == 1
