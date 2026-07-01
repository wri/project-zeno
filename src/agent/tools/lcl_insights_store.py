"""Fetch LCL Insights articles into local storage."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import httpx
import trafilatura
from bs4 import BeautifulSoup

INSIGHTS_INDEX_URL = "https://landcarbonlab.org/insights/"
INSIGHTS_URL_RE = re.compile(r"^https://landcarbonlab\.org/insights/[^/]+/?$")
USER_AGENT = "Mozilla/5.0 (compatible; project-zeno/1.0)"

_SOURCE = "lcl"
_CORPUS_ROOT = Path(__file__).resolve().parents[3] / "data" / "insights"
_DATA_DIR = _CORPUS_ROOT / _SOURCE
_INDEX_PATH = _CORPUS_ROOT / "index.json"


def _make_client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=30.0, follow_redirects=True
    )


def slug_from_url(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


def _parse_meta(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")

    def _content(*, name: str = "", prop: str = "") -> str:
        attrs = {"name": name} if name else {"property": prop}
        tag = soup.find("meta", attrs=attrs)
        return tag["content"].strip() if tag and tag.get("content") else ""

    return {
        "title": _content(name="citation_title") or _content(prop="og:title"),
        "abstract": _content(name="description")
        or _content(prop="og:description"),
        "image": _content(prop="og:image"),
        "image_alt": _content(prop="og:image:alt"),
        "lastmod": _content(prop="article:modified_time")
        or _content(prop="article:published_time"),
    }


def _cite_link(url: str, para_num: int, label: str) -> str:
    return f"[{label}]({url}#p{para_num})"


def _tag_paragraphs(markdown_body: str, url: str) -> str:
    section = ""
    out: list[str] = []
    para_num = 0
    for line in markdown_body.splitlines():
        if line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            if level == 1:
                continue
            section = line.lstrip("# ").strip()
            continue
        if not line.strip():
            out.append("")
            continue
        para_num += 1
        label = (
            f'§{para_num} | Section: "{section}"'
            if section
            else f"§{para_num}"
        )
        out.append(f"{_cite_link(url, para_num, label)} {line}")
    return "\n".join(out).strip()


def list_insight_urls(client: httpx.Client | None = None) -> list[str]:
    own_client = client is None
    if own_client:
        client = _make_client()
    assert client is not None
    try:
        html = client.get(INSIGHTS_INDEX_URL).text
        soup = BeautifulSoup(html, "html.parser")
        seen: set[str] = set()
        urls: list[str] = []
        for a in soup.select("a[href]"):
            href = (a.get("href") or "").strip()
            if not href:
                continue
            full = urljoin(INSIGHTS_INDEX_URL, href).rstrip("/")
            if INSIGHTS_URL_RE.match(full) and full not in seen:
                seen.add(full)
                urls.append(full)
        return urls
    finally:
        if own_client:
            client.close()


def article_to_markdown(
    *,
    url: str,
    html: str,
    title: str = "",
    abstract: str = "",
    lastmod: str = "",
) -> str:
    body_md = trafilatura.extract(
        html, url=url, output_format="markdown", include_comments=False
    )
    if not body_md:
        raise ValueError(f"No article body extracted from {url}")
    if not title:
        first = body_md.splitlines()[0]
        if first.startswith("#"):
            title = first.lstrip("# ").strip()
    tagged = _tag_paragraphs(body_md, url)
    header = [
        f"# {title}",
        "",
        f"**URL:** [{url}]({url})",
        f"**Last modified:** {lastmod or ''}",
        "",
        f"> {abstract}" if abstract else "",
        "",
    ]
    return "\n".join(header) + tagged + "\n"


def load_index() -> list[dict]:
    if not _INDEX_PATH.exists():
        return []
    data = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
    out = [a for a in data.get("articles", []) if a.get("source") == _SOURCE]
    for art in out:
        art["path"] = _DATA_DIR / f"{art['slug']}.md"
    return out


def save_index(articles: list[dict]) -> None:
    _CORPUS_ROOT.mkdir(parents=True, exist_ok=True)
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    existing: list[dict] = []
    if _INDEX_PATH.exists():
        existing = json.loads(_INDEX_PATH.read_text(encoding="utf-8")).get(
            "articles", []
        )
    keep = [a for a in existing if a.get("source") != _SOURCE]
    merged = keep + [
        {
            **{k: v for k, v in art.items() if k != "path"},
            "source": _SOURCE,
            "id": f"{_SOURCE}/{art['slug']}",
        }
        for art in articles
    ]
    payload = {
        "articles": merged,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _INDEX_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def sync_articles(
    limit: int | None = None, force: bool = False
) -> dict[str, int]:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    existing = {a["slug"]: a for a in load_index()}
    stats = {"fetched": 0, "skipped": 0, "failed": 0, "total_listed": 0}
    with _make_client() as client:
        urls = list_insight_urls(client)
        stats["total_listed"] = len(urls)
        if limit is not None:
            urls = urls[:limit]
        for url in urls:
            slug = slug_from_url(url)
            path = _DATA_DIR / f"{slug}.md"
            if not force and path.exists() and slug in existing:
                stats["skipped"] += 1
                continue
            try:
                html = client.get(url).text
                meta = _parse_meta(html)
                markdown = article_to_markdown(
                    url=url,
                    html=html,
                    title=meta["title"],
                    abstract=meta["abstract"],
                    lastmod=meta["lastmod"],
                )
                path.write_text(markdown, encoding="utf-8")
                existing[slug] = {
                    "id": f"{_SOURCE}/{slug}",
                    "source": _SOURCE,
                    "slug": slug,
                    "title": meta["title"],
                    "abstract": meta["abstract"],
                    "url": url,
                    "lastmod": meta["lastmod"],
                    "image": meta["image"],
                    "image_alt": meta["image_alt"],
                    "path": path,
                }
                stats["fetched"] += 1
            except Exception:
                stats["failed"] += 1
    save_index(list(existing.values()))
    return stats
