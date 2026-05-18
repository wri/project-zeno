import functools

from langchain_core.tools import tool

from src.agent.tools.wri_insights_store import (
    articles_dir,
    linkify_citations,
    load_index,
)


@functools.lru_cache(maxsize=1)
def _load_index() -> list[dict]:
    return load_index()


def _score(article: dict, terms: list[str]) -> int:
    slug = article["slug"].lower()
    title = article["title"].lower()
    abstract = article["abstract"].lower()
    score = 0
    for term in terms:
        score += slug.count(term) * 2
        score += title.count(term) * 3
        score += abstract.count(term) * 1
    return score


def _search(query: str, max_results: int) -> list[dict]:
    terms = [t.lower() for t in query.split() if len(t) > 2]
    scored = [(art, _score(art, terms)) for art in _load_index()]
    scored = [(art, s) for art, s in scored if s > 0]
    scored.sort(key=lambda x: -x[1])
    return [art for art, _ in scored[:max_results]]


@tool("wri_insights")
def wri_insights(query: str, max_articles: int = 2) -> str:
    """Search WRI Insights articles and return their full cited content.
    Covers climate, forests, land use, energy, freshwater, food, and ocean topics.
    Paragraphs are tagged with clickable [§N](url#pN) links for precise citation.
    Use when grounding a response in WRI's published research would add value.
    """
    articles_dir_path = articles_dir()
    if not articles_dir_path.exists() or not _load_index():
        return (
            "WRI Insights article index not found. "
            "Run: uv run python scripts/fetch_wri_insights.py --limit 50"
        )

    matches = _search(query, max_articles + 2)
    if not matches:
        return f"No WRI Insights articles found for '{query}'."

    parts = []
    for art in matches[:max_articles]:
        path = art.get("path")
        if path is None or not path.exists():
            continue
        parts.append(linkify_citations(path.read_text(encoding="utf-8")))

    if not parts:
        return f"No WRI Insights articles found for '{query}'."

    return "\n\n---\n\n".join(parts)
