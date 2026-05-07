"""CLI runner for the Zeno harness.

Consumes LangGraph's native streaming (updates + custom events from
stream_writer). No custom session or event system needed.

    uv run python -m src.agent.harness.cli
    uv run python -m src.agent.harness.cli --once "analyze Para for tree cover loss"
    uv run python -m src.agent.harness.cli --once "..." --quiet
    uv run python -m src.agent.harness.cli --once "..." --json
"""

import argparse
import asyncio
import json
from datetime import datetime
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from src.agent.harness.factory import create_zeno_agent

_console = Console()

_WIDTH = 72


def _default(o: Any):
    if isinstance(o, datetime):
        return o.isoformat()
    raise TypeError(f"not json-serializable: {type(o).__name__}")


def _section(label: str, body: str) -> str:
    head = f"--- {label} " + "-" * max(3, _WIDTH - len(label) - 5)
    foot = "-" * _WIDTH
    return f"\n{head}\n{body.rstrip()}\n{foot}"


def _truncate(s: str, limit: int) -> str:
    return s if len(s) <= limit else s[:limit] + "..."


def _render_artifact(a: dict) -> None:
    """Render an artifact using Rich panels and tables."""
    art_id = a.get("id", "?")
    art_type = a.get("type", "?")
    title = a.get("title", "Untitled")
    content = a.get("content", {})
    follow_ups = a.get("follow_ups", [])

    renderables = []

    # Type badge + chart mark
    spec = content.get("spec", {})
    mark = spec.get("mark", art_type)
    renderables.append(Text(f"  [{mark}]", style="dim"))
    renderables.append(Text())

    # Insight
    insight = content.get("insight", "")
    if insight:
        renderables.append(Text.from_markup(f"[bold]Insight:[/bold] {insight}"))
        renderables.append(Text())

    # Data summary as a table
    chart_data = content.get("data", [])
    if chart_data and isinstance(chart_data, list) and len(chart_data) > 0:
        table = Table(
            show_header=True,
            header_style="bold cyan",
            box=None,
            pad_edge=False,
        )
        cols = list(chart_data[0].keys())
        for col in cols:
            table.add_column(col)
        for row in chart_data[:8]:
            table.add_row(*[str(row.get(c, "")) for c in cols])
        if len(chart_data) > 8:
            table.add_row(*["..." for _ in cols])
        renderables.append(table)
        renderables.append(Text())

    # Follow-ups
    if follow_ups:
        renderables.append(Text.from_markup("[bold]Follow-ups:[/bold]"))
        for f in follow_ups:
            renderables.append(Text(f"  - {f}", style="dim"))

    from rich.console import Group
    panel = Panel(
        Group(*renderables) if renderables else Text("(no content)"),
        title=f"[bold]{title}[/bold]",
        subtitle=f"@{art_id}",
        border_style="green" if art_type == "chart" else "blue",
        padding=(1, 2),
    )
    _console.print()
    _console.print(panel)


def _format_custom_event(data: dict, *, verbose: bool) -> str | None:
    """Format a custom event from stream_writer."""
    etype = data.get("type", "unknown")
    if etype == "aoi_resolved":
        refs = data.get("aoi_refs", [])
        names = ", ".join(r.get("name", "?") for r in refs)
        return f"[aoi] {names}"
    if etype == "data_fetched":
        sid = data.get("stat_id", "?")
        meta = data.get("meta", {})
        return (
            f"[data] {sid} "
            f"rows={meta.get('row_count')} "
            f"cols={meta.get('columns')}"
        )
    if etype == "artifact":
        a = data.get("artifact", {})
        _render_artifact(a)
        return None
    if etype == "zoom_map":
        refs = data.get("aoi_refs", [])
        names = ", ".join(r.get("name", "?") for r in refs)
        return f"[zoom] {names}"
    if etype == "context":
        if not verbose:
            return None
        block = data.get("session_block", "")
        count = data.get("message_count", 0)
        return _section(f"context ({count} messages)", block)
    if etype == "thinking":
        return _section("thinking", data.get("text", "")) if verbose else None
    return f"[custom] {json.dumps(data, default=_default)}" if verbose else None


def _format_state_update(update: dict, *, verbose: bool) -> str | None:
    """Format a state update from stream_mode='updates'."""
    if not verbose:
        return None
    filtered = {k: v for k, v in update.items() if k != "messages"}
    if filtered:
        return f"[state] {json.dumps(filtered, default=_default)}"
    return None


def _format_message(msg, *, verbose: bool) -> str | None:
    """Format a message from the updates stream."""
    if isinstance(msg, AIMessage):
        content = msg.content
        if isinstance(content, str) and content.strip():
            return _section("assistant", content.strip())
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        parts.append(block.get("text", ""))
                    elif block.get("type") == "thinking" and verbose:
                        parts.append(f"[thinking] {block.get('thinking', '')[:200]}")
                else:
                    parts.append(str(block))
            text = "\n".join(p for p in parts if p)
            if text:
                return _section("assistant", text)
        if msg.tool_calls and verbose:
            calls = []
            for tc in msg.tool_calls:
                args_str = json.dumps(tc.get("args", {}), default=_default, indent=2)
                calls.append(f"{tc.get('name', '?')}({args_str})")
            return _section("tool_calls", "\n".join(calls))
        return None
    if isinstance(msg, ToolMessage) and verbose:
        body = msg.content if isinstance(msg.content, str) else json.dumps(msg.content, default=_default)
        return _section(f"tool_result <- {msg.name or '?'}", _truncate(body, 800))
    return None


async def _run_query(
    agent, query: str, config: dict, *, verbose: bool, json_mode: bool
) -> None:
    inputs = {"messages": [HumanMessage(content=query)]}
    context_shown = False
    async for event in agent.astream(inputs, config=config, stream_mode=["updates", "custom"]):
        mode, payload = event
        if json_mode:
            print(json.dumps({"mode": mode, "data": payload}, default=_default))
            continue

        if mode == "custom":
            if isinstance(payload, dict) and payload.get("type") == "context":
                if context_shown:
                    continue
                context_shown = True
            out = _format_custom_event(payload, verbose=verbose)
            if out:
                print(out)
        elif mode == "updates":
            if isinstance(payload, dict):
                for _node, update in payload.items():
                    if not isinstance(update, dict):
                        continue
                    state_out = _format_state_update(update, verbose=verbose)
                    if state_out:
                        print(state_out)
                    for msg in update.get("messages") or []:
                        msg_out = _format_message(msg, verbose=verbose)
                        if msg_out:
                            print(msg_out)


async def run_once(query: str, verbose: bool, json_mode: bool) -> None:
    agent = create_zeno_agent()
    config = {"configurable": {"thread_id": "cli"}}
    await _run_query(agent, query, config, verbose=verbose, json_mode=json_mode)


async def run_repl(verbose: bool, json_mode: bool) -> None:
    agent = create_zeno_agent()
    config = {"configurable": {"thread_id": "cli-repl"}}
    print(f"Zeno harness REPL ({'verbose' if verbose else 'quiet'} mode). Ctrl-D to exit.")
    loop = asyncio.get_event_loop()
    while True:
        try:
            line = await loop.run_in_executor(None, input, "> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line.strip():
            continue
        await _run_query(agent, line, config, verbose=verbose, json_mode=json_mode)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", help="run a single query and exit")
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="hide tool calls/results and state updates",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit events as JSON lines instead of formatted sections",
    )
    args = parser.parse_args()
    verbose = not args.quiet
    if args.once:
        asyncio.run(run_once(args.once, verbose, args.json))
    else:
        asyncio.run(run_repl(verbose, args.json))


if __name__ == "__main__":
    main()
