"""CLI runner for the harness.

By default the runner is verbose: every model call shows the prepended
session block and message tail (ContextEvent), every tool invocation
shows its arguments (ToolCallEvent) and return value (ToolResultEvent),
and assistant text plus thinking blocks are printed as they arrive. Pass
--quiet to drop the model-call/tool-call boundaries and only show
business-level events. Pass --json to emit raw events as JSON lines.

    uv run python -m src.agent.harness.cli
    uv run python -m src.agent.harness.cli --once "analyze Para for tree cover loss"
    uv run python -m src.agent.harness.cli --once "..." --quiet
    uv run python -m src.agent.harness.cli --once "..." --json
"""

import argparse
import asyncio
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any

from src.agent.harness.backends.memory import InMemoryBackend
from src.agent.harness.factory import create_zeno_agent
from src.agent.harness.protocol import (
    AoiResolvedEvent,
    ArtifactEvent,
    ContextEvent,
    DataFetchedEvent,
    ErrorEvent,
    MessageEvent,
    StateDeltaEvent,
    ThinkingEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from src.agent.harness.session import ZenoSession

_WIDTH = 72


def _default(o: Any):
    if is_dataclass(o):
        return asdict(o)
    if isinstance(o, datetime):
        return o.isoformat()
    raise TypeError(f"not json-serializable: {type(o).__name__}")


def _section(label: str, body: str) -> str:
    head = f"─── {label} " + "─" * max(3, _WIDTH - len(label) - 5)
    foot = "─" * _WIDTH
    return f"\n{head}\n{body.rstrip()}\n{foot}"


def _truncate(s: str, limit: int) -> str:
    return s if len(s) <= limit else s[:limit] + "…"


def _format_context(ev: ContextEvent) -> str:
    lines = [ev.system_block.rstrip(), "", f"history: {ev.message_count} messages"]
    if ev.recent:
        lines.append("recent tail:")
        for m in ev.recent:
            head = f"  [{m.role}]"
            if m.text:
                head += f" {_truncate(m.text, 200)}"
            if m.tool_calls:
                head += f"  tool_calls=[{', '.join(m.tool_calls)}]"
            lines.append(head)
    return _section("context (turn → orchestrator)", "\n".join(lines))


def _format_tool_call(ev: ToolCallEvent) -> str:
    args_str = json.dumps(ev.args, default=_default, indent=2, sort_keys=True)
    body = f"{ev.name}({args_str})"
    if ev.call_id:
        body += f"\n  id={ev.call_id}"
    return _section(f"tool_call → {ev.name}", body)


def _format_tool_result(ev: ToolResultEvent) -> str:
    if isinstance(ev.result, str):
        body = ev.result
    else:
        try:
            body = json.dumps(ev.result, default=_default, indent=2, sort_keys=True)
        except (TypeError, ValueError):
            body = str(ev.result)
    return _section(f"tool_result ← {ev.name}", _truncate(body, 1200))


def _format(event, *, verbose: bool) -> str | None:
    if isinstance(event, ContextEvent):
        return _format_context(event) if verbose else None
    if isinstance(event, ToolCallEvent):
        return _format_tool_call(event) if verbose else None
    if isinstance(event, ToolResultEvent):
        return _format_tool_result(event) if verbose else None
    if isinstance(event, MessageEvent):
        return _section(f"message ({event.role})", event.content)
    if isinstance(event, ThinkingEvent):
        return _section("thinking", event.text)
    if isinstance(event, AoiResolvedEvent):
        names = ", ".join(r.get("name", "?") for r in event.aoi_refs)
        return f"[aoi] {names}"
    if isinstance(event, DataFetchedEvent):
        return (
            f"[data] {event.stat_id} "
            f"rows={event.meta.get('row_count')} "
            f"cols={event.meta.get('columns')}"
        )
    if isinstance(event, ArtifactEvent):
        a = event.artifact
        return f"[artifact] {a.id} type={a.type} title={a.title!r}"
    if isinstance(event, StateDeltaEvent):
        return f"[state] {json.dumps(event.update, default=_default)}"
    if isinstance(event, ErrorEvent):
        return f"[error] {event.message}"
    return f"[?] {event}"


async def _run_query(session: ZenoSession, query: str, *, verbose: bool, json_mode: bool) -> None:
    async for event in session.stream(query):
        if json_mode:
            print(json.dumps(asdict(event), default=_default))
            continue
        out = _format(event, verbose=verbose)
        if out is not None:
            print(out)


async def run_once(query: str, verbose: bool, json_mode: bool) -> None:
    backend = InMemoryBackend()
    agent = create_zeno_agent(backend=backend)
    session = ZenoSession(agent=agent, backend=backend)
    await _run_query(session, query, verbose=verbose, json_mode=json_mode)


async def run_repl(verbose: bool, json_mode: bool) -> None:
    backend = InMemoryBackend()
    agent = create_zeno_agent(backend=backend)
    session = ZenoSession(agent=agent, backend=backend)
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
        await _run_query(session, line, verbose=verbose, json_mode=json_mode)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", help="run a single query and exit")
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="hide context / tool_call / tool_result sections",
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
