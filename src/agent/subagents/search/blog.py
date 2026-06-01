"""WRI Blog Search using deep agents with FilesystemBackend.

Usage:
    uv run python -m src.agent.subagents.search.blog "renewable energy in Africa"
    uv run python -m src.agent.subagents.search.blog --model anthropic:claude-haiku-4-6 "forest fires"
"""

from __future__ import annotations

import argparse
import logging
import time
import warnings
from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend

DATA_DIR = Path(__file__).resolve().parents[4] / "data" / "wri_insights"
DEFAULT_MODEL = "google_genai:gemini-3.5-flash"
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

1. **Understand the query** — identify the key topics, entities, and intent.
2. **Search broadly** — use `grep` to find articles mentioning key terms.
   Try multiple search terms if the first attempt yields few results.
3. **Narrow down** — read the top candidate articles to verify relevance.
4. **Synthesize** — write a concise answer citing specific paragraphs.

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


def create_search_agent(model: str = DEFAULT_MODEL) -> Any:
    """Create a deep agent backed by the local articles directory."""
    return create_deep_agent(
        model=model,
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


def run_search(query: str, model: str = DEFAULT_MODEL) -> dict:
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
        default=DEFAULT_MODEL,
        help=f"Model to use (default: {DEFAULT_MODEL})",
    )
    args = parser.parse_args()

    print(f"Query: {args.query}")
    print(f"Model: {args.model}")
    print()

    result = run_search(args.query, model=args.model)

    print(
        f"{result['elapsed_s']}s | {result['n_messages']} messages | "
        f"{result['input_tokens']} in + {result['output_tokens']} out = {result['total_tokens']} tokens"
    )


if __name__ == "__main__":
    main()
