"""Fetch WRI Insights articles from the sitemap into local storage."""

from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx
import trafilatura
from bs4 import BeautifulSoup

SITEMAP_INDEX = "https://www.wri.org/sitemap.xml"
INSIGHTS_URL_RE = re.compile(r"^https://www\.wri\.org/insights/[^/]+$")
_CITE_TAG_RE = re.compile(r'\[(§\d+(?:\s*\|\s*Section:\s*"[^"]*")?)\](?!\()')
_URL_HEADER_RE = re.compile(
    r"^\*\*URL:\*\*\s+(https?://\S+)\s*$", re.MULTILINE
)
SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
USER_AGENT = "Mozilla/5.0 (compatible; project-zeno/1.0)"

_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "wri_insights"
_INDEX_PATH = _DATA_DIR / "index.json"


def articles_dir() -> Path:
    return _DATA_DIR


def index_path() -> Path:
    return _INDEX_PATH


def list_insight_urls(
    client: httpx.Client | None = None,
) -> list[tuple[str, str]]:
    """Return (url, lastmod) for every /insights/ page in the WRI sitemap."""
    own_client = client is None
    if own_client:
        client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=30.0,
            follow_redirects=True,
        )
    assert client is not None
    try:
        index_xml = client.get(SITEMAP_INDEX).content
        root = ET.fromstring(index_xml)
        sub_sitemaps = [
            loc.text
            for loc in root.findall(".//sm:sitemap/sm:loc", SITEMAP_NS)
            if loc.text
        ]

        all_urls: list[tuple[str, str]] = []
        for sm_url in sub_sitemaps:
            sitemap_xml = client.get(sm_url).content
            sm_root = ET.fromstring(sitemap_xml)
            for url_el in sm_root.findall(".//sm:url", SITEMAP_NS):
                loc = url_el.findtext(
                    "sm:loc", default="", namespaces=SITEMAP_NS
                )
                lastmod = url_el.findtext(
                    "sm:lastmod", default="", namespaces=SITEMAP_NS
                )
                if loc and INSIGHTS_URL_RE.match(loc):
                    all_urls.append((loc, lastmod))

        by_url: dict[str, str] = {}
        for url, lastmod in all_urls:
            if url not in by_url or lastmod > by_url[url]:
                by_url[url] = lastmod

        return sorted(by_url.items(), key=lambda x: x[1], reverse=True)
    finally:
        if own_client:
            client.close()


def slug_from_url(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


def _parse_meta(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.find("meta", attrs={"name": "citation_title"})
    desc_el = soup.find("meta", attrs={"name": "description"})
    title = (
        title_el["content"].strip()
        if title_el and title_el.get("content")
        else ""
    )
    abstract = (
        desc_el["content"].strip()
        if desc_el and desc_el.get("content")
        else ""
    )
    return title, abstract


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
        if section:
            label = f'§{para_num} | Section: "{section}"'
        else:
            label = f"§{para_num}"
        out.append(f"{_cite_link(url, para_num, label)} {line}")

    return "\n".join(out).strip()


def _article_url(markdown: str) -> str:
    for line in markdown.splitlines()[:12]:
        match = _URL_HEADER_RE.match(line)
        if match:
            return match.group(1)
    return ""


def linkify_citations(markdown: str) -> str:
    """Turn [§N] tags and plain URL headers into clickable markdown links."""
    url = _article_url(markdown)
    if not url:
        return markdown

    def _link_tag(match: re.Match[str]) -> str:
        label = match.group(1)
        para_num = int(label.removeprefix("§").split("|", 1)[0].strip())
        return _cite_link(url, para_num, label)

    linked = _CITE_TAG_RE.sub(_link_tag, markdown)
    return _URL_HEADER_RE.sub(f"**URL:** [{url}]({url})", linked, count=1)


def article_to_markdown(
    *, url: str, lastmod: str, html: str, title: str = "", abstract: str = ""
) -> str:
    if not title or not abstract:
        meta_title, meta_abstract = _parse_meta(html)
        title = title or meta_title
        abstract = abstract or meta_abstract

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
        f"**Last modified:** {lastmod}",
        "",
        f"> {abstract}" if abstract else "",
        "",
    ]
    return "\n".join(header) + tagged + "\n"


def fetch_article(
    client: httpx.Client, url: str, lastmod: str
) -> tuple[str, dict]:
    """Download one article and return (markdown, index entry)."""
    slug = slug_from_url(url)
    response = client.get(url)
    response.raise_for_status()
    html = response.text
    title, abstract = _parse_meta(html)
    markdown = article_to_markdown(
        url=url, lastmod=lastmod, html=html, title=title, abstract=abstract
    )
    entry = {
        "slug": slug,
        "title": title,
        "abstract": abstract,
        "url": url,
        "lastmod": lastmod,
    }
    return markdown, entry


def load_index() -> list[dict]:
    if _INDEX_PATH.exists():
        data = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
        articles = data.get("articles", [])
        for art in articles:
            art["path"] = _DATA_DIR / f"{art['slug']}.md"
        return articles

    if not _DATA_DIR.exists():
        return []

    index = []
    for path in sorted(_DATA_DIR.glob("*.md")):
        lines = path.read_text(encoding="utf-8").splitlines()
        title = lines[0].lstrip("# ").strip() if lines else path.stem
        url = abstract = lastmod = ""
        for line in lines[1:12]:
            if line.startswith("**URL:**"):
                raw = line.replace("**URL:**", "").strip()
                md_match = re.match(r"\[([^\]]+)\]\(([^)]+)\)", raw)
                url = md_match.group(2) if md_match else raw
            elif line.startswith("**Last modified:**"):
                lastmod = line.replace("**Last modified:**", "").strip()
            elif line.startswith(">"):
                abstract = line.lstrip("> ").strip()
        index.append(
            {
                "slug": path.stem,
                "title": title,
                "abstract": abstract,
                "url": url,
                "lastmod": lastmod,
                "path": path,
            }
        )
    return index


def save_index(articles: list[dict]) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "articles": [
            {k: v for k, v in art.items() if k != "path"} for art in articles
        ],
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _INDEX_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _make_client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=30.0, follow_redirects=True
    )


_thread_local = threading.local()
_worker_clients: list[httpx.Client] = []
_worker_clients_lock = threading.Lock()


def _init_fetch_worker() -> None:
    client = _make_client()
    _thread_local.client = client
    with _worker_clients_lock:
        _worker_clients.append(client)


def _close_worker_clients() -> None:
    with _worker_clients_lock:
        for client in _worker_clients:
            client.close()
        _worker_clients.clear()


def _pending_jobs(
    urls: list[tuple[str, str]],
    *,
    force: bool,
    existing: dict[str, dict],
) -> tuple[list[tuple[str, str]], int]:
    pending: list[tuple[str, str]] = []
    skipped = 0
    for url, lastmod in urls:
        slug = slug_from_url(url)
        path = _DATA_DIR / f"{slug}.md"
        prev = existing.get(slug)
        if (
            not force
            and path.exists()
            and prev
            and prev.get("lastmod") == lastmod
        ):
            skipped += 1
            continue
        pending.append((url, lastmod))
    return pending, skipped


def _fetch_and_save(
    url: str, lastmod: str, *, delay_s: float
) -> tuple[str, dict]:
    if delay_s:
        time.sleep(delay_s)
    client: httpx.Client = _thread_local.client
    slug = slug_from_url(url)
    path = _DATA_DIR / f"{slug}.md"
    markdown, entry = fetch_article(client, url, lastmod)
    path.write_text(markdown, encoding="utf-8")
    entry["path"] = path
    return slug, entry


def sync_articles(
    *,
    limit: int | None = None,
    force: bool = False,
    delay_s: float = 0.25,
    workers: int = 1,
) -> dict[str, int]:
    """Fetch insights from the sitemap into data/wri_insights/."""
    if workers < 1:
        raise ValueError("workers must be >= 1")

    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    existing = {a["slug"]: a for a in load_index()}
    stats = {"fetched": 0, "skipped": 0, "failed": 0, "total_listed": 0}
    stats_lock = threading.Lock()

    with _make_client() as client:
        urls = list_insight_urls(client)
        stats["total_listed"] = len(urls)
        if limit is not None:
            urls = urls[:limit]

    pending, skipped = _pending_jobs(urls, force=force, existing=existing)
    stats["skipped"] = skipped

    if workers == 1:
        with _make_client() as client:
            for url, lastmod in pending:
                slug = slug_from_url(url)
                path = _DATA_DIR / f"{slug}.md"
                try:
                    markdown, entry = fetch_article(client, url, lastmod)
                    path.write_text(markdown, encoding="utf-8")
                    entry["path"] = path
                    existing[slug] = entry
                    stats["fetched"] += 1
                except Exception:
                    stats["failed"] += 1
                if delay_s:
                    time.sleep(delay_s)
    else:
        try:
            with ThreadPoolExecutor(
                max_workers=workers, initializer=_init_fetch_worker
            ) as pool:
                futures = {
                    pool.submit(
                        _fetch_and_save, url, lastmod, delay_s=delay_s
                    ): (
                        url,
                        lastmod,
                    )
                    for url, lastmod in pending
                }
                for future in as_completed(futures):
                    try:
                        slug, entry = future.result()
                    except Exception:
                        with stats_lock:
                            stats["failed"] += 1
                        continue
                    existing[slug] = entry
                    with stats_lock:
                        stats["fetched"] += 1
        finally:
            _close_worker_clients()

    save_index(list(existing.values()))
    return stats
