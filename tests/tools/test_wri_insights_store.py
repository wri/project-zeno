from src.agent.tools.wri_insights_store import linkify_citations

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
