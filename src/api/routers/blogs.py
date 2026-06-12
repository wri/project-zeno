"""Card metadata lookup for WRI Insights links in agent replies."""

from functools import lru_cache

from fastapi import APIRouter, Query

from src.agent.tools.wri_insights_store import load_index, slug_from_url

router = APIRouter()


@lru_cache(maxsize=1)
def _articles_by_slug() -> dict[str, dict]:
    return {a["slug"]: a for a in load_index()}


@router.get("/api/blogs/metadata")
async def blog_metadata(
    url: list[str] = Query(
        ...,
        description="WRI Insights article URLs (repeat the param per URL)",
    ),
) -> dict:
    """
    Resolve wri.org/insights URLs to card metadata.

    Returns an `articles` object keyed by the requested URL strings, so the
    frontend can map markdown links in a reply directly to cards. URLs with
    query strings or fragments resolve to the same article; unknown URLs are
    omitted from the response.
    """
    index = _articles_by_slug()
    articles = {}
    for u in url:
        slug = slug_from_url(u.split("#", 1)[0].split("?", 1)[0])
        a = index.get(slug)
        if a is None:
            continue
        articles[u] = {
            "slug": a["slug"],
            "title": a["title"],
            "abstract": a["abstract"],
            "url": a["url"],
            "lastmod": a["lastmod"],
            "image": a.get("image", ""),
            "image_alt": a.get("image_alt", ""),
        }
    return {"articles": articles}
