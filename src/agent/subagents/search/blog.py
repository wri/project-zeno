"""WRI Blog Search using deep agents with FilesystemBackend.

Usage:
    uv run python -m src.agent.subagents.search.blog "renewable energy in Africa"
    uv run python -m src.agent.subagents.search.blog --model sonnet "forest fires"
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
import warnings
from functools import lru_cache
from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import tool

from src.agent.llms import MODEL_REGISTRY, SMALL_MODEL
from src.agent.utils.sgrep import DEFAULT_INDEX_DIR, TAG_RE, query_index

DATA_DIR = Path(__file__).resolve().parents[4] / "data" / "wri_insights"
DEFAULT_MODEL = SMALL_MODEL
BLOG_SEARCH_PROMPT = """\
You are a WRI (World Resources Institute) research assistant.
Your job is to search through a library of WRI Insights blog articles
and answer the user's question with well-cited, accurate information.

## Data layout

You have access to a directory of markdown (.md) files.
- `index.json` contains metadata for all articles: slug, title, abstract, url, lastmod.
- Each article is stored as `<slug>.md` with the full text.
- Articles are tagged with paragraph citations like [§N](url#pN).

## Your workflow

Do ONE round of searching, shortlist, read only what's promising, then answer.
Do NOT run repeated series of lookups.

1. **Understand the query** — identify the key topics, entities, and intent.
2. **Search (required)** — you MUST use BOTH tools (~5 results each):
   - `sgrep` — semantic search; finds paragraphs by meaning even when exact
     keywords don't match. Run it ONCE.
   - `grep` — exact/regex keyword search (ripgrep); best for specific terms,
     names, acronyms, or numbers. Run it a couple of times with different
     query phrasings.
   Run `sgrep` once, then `grep` with 2-3 MAX different query phrasings, be aware this
   is an exact search operation.
3. **Shortlist & read** — collect the candidate slugs from the search results.
   Use `article_meta` to read their titles/abstracts and decide which are
   genuinely relevant, then `read_file` only those promising articles.
4. **Answer** — synthesize a concise, well-cited answer from what you read.

## Citation format

When citing, use the existing paragraph links from the articles:
[§N](url#pN) — always include the full URL from the article.

## Guidelines

- Be thorough but concise. Aim for 2-5 relevant articles.
- If no articles match, say so clearly.
- Do NOT invent or hallucinate article content.
- Prefer recent articles (check lastmod dates) when multiple are relevant.
- Answer in the same language as the query.
"""


def _silence_logs() -> None:
    """Suppress noisy HTTP, SDK, and library logs."""
    logging.basicConfig(level=logging.WARNING)
    for name in (
        "httpx",
        "httpcore",
        "anthropic",
        "openai",
        "langchain",
        "langgraph",
        "langsmith",
        "src",
        "asyncio",
    ):
        logging.getLogger(name).setLevel(logging.WARNING)
    warnings.filterwarnings("ignore")


@lru_cache(maxsize=1)
def _article_index() -> dict[str, dict]:
    """Load index.json once, keyed by slug."""
    data = json.loads((DATA_DIR / "index.json").read_text(encoding="utf-8"))
    return {a["slug"]: a for a in data["articles"]}


@tool
def article_meta(slugs: list[str]) -> str:
    """Look up metadata (title, abstract, url, lastmod) for shortlisted articles.

    Use this to decide whether an article is worth reading in full, instead of
    opening the large index.json yourself. Accepts article slugs or filenames
    (the "<slug>.md" paths returned by sgrep/grep).

    Args:
        slugs: Article slugs or "<slug>.md" filenames to look up.
    """
    index = _article_index()
    lines = []
    for s in slugs:
        slug = s[:-3] if s.endswith(".md") else s
        a = index.get(slug)
        if a is None:
            lines.append(f"{slug}: not found")
        else:
            lines.append(
                f"{slug} ({a['lastmod']})\n  {a['title']}\n  {a['abstract']}\n  {a['url']}"
            )
    return "\n".join(lines)


def _snippet(text: str, max_words: int = 30) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + " …"


@tool
def sgrep(query: str, top: int = 5) -> str:
    """Semantic search over the WRI blog articles.

    Finds the most relevant paragraphs by meaning, even when exact keywords
    don't match. Returns matches as "<file> §N (<score>): <snippet>" lines,
    where <file> is the article path you can pass to read_file and §N the
    paragraph number within it.

    Args:
        query: Natural-language search query.
        top: Maximum number of paragraphs to return (default: 5).
    """
    results = query_index(DEFAULT_INDEX_DIR, query, k=top)
    if not results:
        return "No matching paragraphs found."
    lines = []
    for r in results:
        loc = f"§{r['para']}" if r.get("para") else f":{r['line']}"
        section = f" [{r['section']}]" if r.get("section") else ""
        lines.append(
            f"{r['file']} {loc} ({r['score']:.2f}){section}: {_snippet(r['text'])}"
        )
    return "\n".join(lines)


def _md_link_target(raw: str) -> str:
    """Return the URL from a '[text](url)' markdown link or the raw string."""
    m = re.match(r"\[[^\]]*\]\(([^)]+)\)", raw)
    return m.group(1) if m else raw


@tool
def read_paragraphs(slug: str, paras: list[int], context: int = 1) -> str:
    """Read specific paragraphs of an article by their §N numbers.

    Much cheaper than read_file: returns only the requested paragraphs plus
    `context` neighbours on each side, along with the article title and URL.
    Use the §N numbers returned by sgrep and grep_articles.

    Args:
        slug: Article slug or "<slug>.md" filename.
        paras: Paragraph numbers to read (e.g. [3, 7]).
        context: Neighbouring paragraphs to include on each side (default: 1).
    """
    slug = slug[:-3] if slug.endswith(".md") else slug
    path = DATA_DIR / f"{slug}.md"
    if not path.exists():
        return f"{slug}: article not found"

    title = url = ""
    by_num: dict[int, tuple[str | None, str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# ") and not title:
            title = line[2:].strip()
        elif line.startswith("**URL:**") and not url:
            url = _md_link_target(line.removeprefix("**URL:**").strip())
        else:
            m = TAG_RE.match(line)
            if m:
                by_num[int(m.group("para"))] = (
                    m.group("section"),
                    m.group("text"),
                )

    wanted = sorted(
        {
            n
            for p in paras
            for n in range(p - context, p + context + 1)
            if n in by_num
        }
    )
    if not wanted:
        return f"{slug}: no such paragraphs (article has §1-§{max(by_num, default=0)})"

    out = [title, f"URL: {url}", ""]
    prev_n: int | None = None
    prev_section: str | None = None
    for n in wanted:
        section, text = by_num[n]
        if prev_n is not None and n > prev_n + 1:
            out.append("[...]")
        if section and section != prev_section:
            out.append(f"## {section}")
        out.append(f"[§{n}] {text}")
        prev_n, prev_section = n, section
    return "\n".join(out)


def _match_window(text: str, match: re.Match, words: int = 12) -> str:
    """Return ~`words` words of context on each side of the match."""
    before = text[: match.start()].split()
    after = text[match.end() :].split()
    snippet = " ".join(
        [*before[-words:], text[match.start() : match.end()], *after[:words]]
    ).strip()
    prefix = "… " if len(before) > words else ""
    suffix = " …" if len(after) > words else ""
    return prefix + snippet + suffix


@tool
def grep_articles(pattern: str, max_results: int = 10) -> str:
    """Keyword/regex search over the WRI blog articles (case-insensitive).

    Best for specific terms, names, acronyms, or numbers. Returns matches as
    "<file> §N: …snippet…" lines with a short window around the match; pass
    the file and §N to read_paragraphs to read the full paragraphs.

    Args:
        pattern: Regular expression (or plain keywords) to search for.
        max_results: Maximum number of matching paragraphs (default: 10).
    """
    try:
        rx = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        return f"Invalid pattern: {exc}"

    out: list[str] = []
    for path in sorted(DATA_DIR.glob("*.md")):
        per_file = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            m = TAG_RE.match(line)
            text = m.group("text") if m else line
            hit = rx.search(text)
            if not hit:
                continue
            loc = f" §{m.group('para')}" if m else ""
            out.append(f"{path.name}{loc}: {_match_window(text, hit)}")
            per_file += 1
            if per_file >= 2:
                break
        if len(out) >= max_results:
            break
    if not out:
        return "No matches found."
    return "\n".join(out[:max_results])


def create_search_agent(model: str | BaseChatModel = DEFAULT_MODEL) -> Any:
    """Create a deep agent backed by the local articles directory."""
    return create_deep_agent(
        model=model,
        tools=[sgrep, grep_articles, read_paragraphs, article_meta],
        backend=FilesystemBackend(
            root_dir=str(DATA_DIR),
            virtual_mode=True,
        ),
        system_prompt=BLOG_SEARCH_PROMPT,
        name="blog-search",
    )


def _extract_text(msg) -> str:
    """Extract text content from an AI message."""
    if isinstance(msg.content, str):
        return msg.content.strip()
    if isinstance(msg.content, list):
        return " ".join(
            b.get("text", "")
            for b in msg.content
            if isinstance(b, dict) and b.get("type") == "text"
        ).strip()
    return ""


@lru_cache(maxsize=1)
def _cached_agent(model: str | BaseChatModel = DEFAULT_MODEL) -> Any:
    return create_search_agent(model=model)


@tool("search_blogs")
async def search_blogs(query: str) -> str:
    """Search WRI Insights blog articles and return a synthesized, cited answer.

    Runs a dedicated research agent that semantically and keyword-searches the
    local WRI Insights corpus, reads the most relevant articles, and writes a
    concise answer with markdown citations to wri.org/insights. Use to ground a
    response in WRI's published research or to explore a topic before analysis.

    Args:
        query: The topic or question to research (a place or theme helps).
    """
    result = await _cached_agent().ainvoke(
        {"messages": [{"role": "user", "content": query}]}
    )
    messages = result.get("messages", [])
    for msg in reversed(messages):
        if type(msg).__name__ == "AIMessage":
            text = _extract_text(msg)
            if text:
                return text
    return "No answer produced by the blog search."


def run_search(query: str, model: str | BaseChatModel = DEFAULT_MODEL) -> dict:
    """Run a search with streaming step-by-step output."""
    agent = create_search_agent(model=model)

    step_num = 0
    t0 = time.perf_counter()
    answer = ""
    n_messages = 0
    total_input_tokens = 0
    total_output_tokens = 0

    for chunk in agent.stream(
        {"messages": [{"role": "user", "content": query}]},
        stream_mode="updates",
    ):
        for _, updates in chunk.items():
            if updates is None:
                continue
            raw_messages = updates.get("messages", [])
            if hasattr(raw_messages, "value"):
                raw_messages = raw_messages.value
            if not isinstance(raw_messages, list):
                raw_messages = [raw_messages]

            for msg in raw_messages:
                n_messages += 1
                msg_type = type(msg).__name__

                if msg_type == "AIMessage":
                    usage = getattr(msg, "usage_metadata", None)
                    if usage:
                        total_input_tokens += usage.get("input_tokens", 0)
                        total_output_tokens += usage.get("output_tokens", 0)

                    text = _extract_text(msg)
                    tool_calls = getattr(msg, "tool_calls", [])

                    if text or tool_calls:
                        step_num += 1
                        print(f"[Step {step_num}]")

                    if text:
                        print(text)

                    for tc in tool_calls:
                        args_str = ", ".join(
                            f"{k}={v}" for k, v in tc["args"].items()
                        )
                        print(f"  -> {tc['name']}({args_str})")

                    if not tool_calls and text:
                        answer = text

                elif msg_type == "ToolMessage":
                    content = (
                        msg.content
                        if isinstance(msg.content, str)
                        else str(msg.content)
                    )
                    words = content.split()
                    if len(words) > 50:
                        print(
                            " ".join(words[:50])
                            + f" ... ({len(words) - 50} more words)"
                        )
                    else:
                        print(content)

    elapsed = time.perf_counter() - t0
    total_tokens = total_input_tokens + total_output_tokens
    return {
        "elapsed_s": round(elapsed, 2),
        "n_messages": n_messages,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "total_tokens": total_tokens,
        "answer": answer,
    }


def main() -> None:
    _silence_logs()
    parser = argparse.ArgumentParser(description="WRI Blog Search")
    parser.add_argument("query", help="Search query")
    parser.add_argument(
        "--model",
        default=None,
        choices=sorted(MODEL_REGISTRY),
        help="Model name from the registry (default: configured small model)",
    )
    args = parser.parse_args()

    model = MODEL_REGISTRY[args.model] if args.model else DEFAULT_MODEL

    print(f"Query: {args.query}")
    print(f"Model: {args.model or 'small (default)'}")
    print()

    result = run_search(args.query, model=model)

    print(
        f"{result['elapsed_s']}s | {result['n_messages']} messages | "
        f"{result['input_tokens']} in + {result['output_tokens']} out = {result['total_tokens']} tokens"
    )


if __name__ == "__main__":
    main()
