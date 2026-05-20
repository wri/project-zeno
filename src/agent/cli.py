#!/usr/bin/env python3
"""Run the Zeno agent from the terminal for prompt iteration and debugging.

Examples:
    uv run python src/agent/cli.py -q "Tree cover loss in Para, Brazil"
    uv run python src/agent/cli.py -f prompts/experiment.txt -i
    uv run python src/agent/cli.py --show-prompt
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

import click
import structlog
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select

from src.agent.graph import (
    close_checkpointer_pool,
    fetch_zeno,
    fetch_zeno_anonymous,
    get_checkpointer_pool,
    get_prompt,
)
from src.agent.tools.pull_data import fetch_statistics_from_url
from src.api.data_models import UserOrm
from src.shared.database import (
    close_global_pool,
    get_session_from_pool,
    initialize_global_pool,
)
from src.shared.logging_config import bind_request_logging_context

DEFAULT_CLI_USER_ID = "zeno-default-user"

STATE_KEYS = (
    "aoi_selection",
    "dataset",
    "insight_id",
    "charts_data",
    "start_date",
    "end_date",
)

# How many rows of pulled / chart data to print (head only).
DATA_HEAD_ROWS = 5

# node_name from LangGraph stream → short label (verbose mode only)
_NODE_LABELS = {
    "model": "model",
    "tools": "tools",
}

_TOOL_ACTION_LABELS = {
    "read_skill": "Reading skill",
    "pick_aoi": "Selecting area",
    "pick_dataset": "Choosing dataset",
    "pull_data": "Fetching data",
    "generate_insights": "Generating insights",
}


def _format_tool_args(args: Any, max_len: int = 200) -> str:
    text = str(args)
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def format_tool_action(name: str, args: dict[str, Any]) -> str:
    """One-line description of an agent tool call for CLI output."""
    label = _TOOL_ACTION_LABELS.get(name, name.replace("_", " ").title())
    if name == "read_skill":
        skill_name = args.get("name", "?")
        if skill_name == "capabilities":
            return "Loading capabilities"
        return f"{label}: {skill_name}"
    if name == "pick_aoi":
        question = args.get("question")
        if question:
            return f"{label}: {question}"
    if name == "pick_dataset":
        query = args.get("query")
        if query:
            return f"{label}: {query}"
    if name == "pull_data":
        query = args.get("query")
        if query:
            return f"{label}: {query}"
        parts = []
        if args.get("start_date"):
            parts.append(str(args["start_date"]))
        if args.get("end_date"):
            parts.append(str(args["end_date"]))
        if parts:
            return f"{label}: {' – '.join(parts)}"
    if name == "generate_insights":
        return label
    if args:
        return f"{label}({_format_tool_args(args, 80)})"
    return label


def format_message_content(msg: BaseMessage) -> str:
    """Human-readable message body (handles Gemini content blocks)."""
    text = getattr(msg, "text", None)
    if isinstance(text, str):
        stripped = text.strip()
        if stripped:
            return stripped

    content = msg.content
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text" and block.get("text"):
                    parts.append(str(block["text"]))
                elif block.get("type") == "thinking" and block.get("thinking"):
                    parts.append(str(block["thinking"]))
            elif isinstance(block, str) and block.strip():
                parts.append(block)
        return "\n".join(parts).strip() if parts else ""
    return ""


def _first_matching_line(content: str, pattern: str) -> Optional[str]:
    for line in content.splitlines():
        match = re.search(pattern, line, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def format_tool_outcome(name: str, content: str) -> str:
    """Short summary of a tool result for CLI output."""
    text = content.strip()
    if not text:
        return "Done (no output)"

    if name == "read_skill":
        if text.startswith("skill not found"):
            return text
        if text.startswith("## About me") or text.startswith("ABOUT ME:"):
            return "Capabilities loaded"
        return "Skill loaded"

    if name == "pick_aoi":
        lines = [
            ln.strip().removeprefix("- ").strip()
            for ln in text.splitlines()
            if ln.strip().startswith("-")
        ]
        if lines:
            return ", ".join(lines)
        return (
            _first_matching_line(text, r"AOI selection name:\s*(.+)")
            or text[:120]
        )

    if name == "pick_dataset":
        dataset = _first_matching_line(text, r"Selected dataset name:\s*(.+)")
        layer = _first_matching_line(text, r"Selected context layer:\s*(.+)")
        reason = _first_matching_line(text, r"Reasoning for selection:\s*(.+)")
        parts = [
            p
            for p in (dataset, layer if layer and layer != "None" else None)
            if p
        ]
        summary = " · ".join(parts) if parts else text[:120]
        if reason:
            return f"{summary}\n      {reason}"
        return summary

    if name == "pull_data":
        if "|" in text:
            text = text.split("|", 1)[0].strip()
        first = text.splitlines()[0].strip()
        return first[:200] if first else "Data pulled"

    if name == "generate_insights":
        finding = _first_matching_line(text, r"Key Finding:\s*(.+)")
        charts = re.search(r"Generated (\d+) chart", text, re.IGNORECASE)
        if finding and charts:
            return f"{charts.group(1)} chart(s) — {finding}"
        if finding:
            return finding
        return text.splitlines()[0][:200]

    if len(text) <= 200:
        return text
    return text[:197] + "…"


def format_state_line(key: str, value: Any) -> Optional[str]:
    """Human-readable snapshot of graph state after a tool step."""
    if not value:
        return None
    if key == "aoi_selection" and isinstance(value, dict):
        return f"Area: {value.get('name', value)}"
    if key == "dataset" and isinstance(value, dict):
        name = (
            value.get("dataset_name")
            or f"dataset #{value.get('dataset_id', '?')}"
        )
        start = value.get("start_date")
        end = value.get("end_date")
        if start and end:
            return f"Dataset: {name} ({start} – {end})"
        return f"Dataset: {name}"
    if key == "insight_id":
        return f"Insight id: {value}"
    if key in ("start_date", "end_date"):
        return None
    if key == "charts_data" and isinstance(value, list):
        n = len(value)
        return f"{n} chart{'s' if n != 1 else ''} ready"
    return None


@contextmanager
def cli_logging(quiet: bool) -> Iterator[None]:
    """Raise console log threshold during CLI runs unless --verbose."""
    root = logging.getLogger()
    stream_handlers = [
        h
        for h in root.handlers
        if isinstance(h, logging.StreamHandler)
        and h.stream in (sys.stdout, sys.stderr)
    ]
    saved_levels = [(h, h.level) for h in stream_handlers]
    saved_loggers: list[tuple[str, int]] = []
    if quiet:
        for handler in stream_handlers:
            handler.setLevel(logging.WARNING)
        for logger_name in (
            "httpx",
            "httpcore",
            "google",
            "google_genai",
            "langchain",
            "langgraph",
        ):
            lg = logging.getLogger(logger_name)
            saved_loggers.append((logger_name, lg.level))
            lg.setLevel(logging.WARNING)
    try:
        yield
    finally:
        for handler, level in saved_levels:
            handler.setLevel(level)
        for logger_name, level in saved_loggers:
            logging.getLogger(logger_name).setLevel(level)


class _CliPrinter:
    def __init__(self, *, verbose: bool) -> None:
        self.verbose = verbose
        self._pending_tools: dict[str, str] = {}
        # Last session block printed — used to skip unchanged repeats so the
        # block shows only when the live state actually evolves.
        self._last_session_block: Optional[str] = None

    def register_tool_calls(self, msg: AIMessage) -> None:
        for tool_call in msg.tool_calls or []:
            call_id = tool_call.get("id")
            name = tool_call.get("name", "?")
            if call_id:
                self._pending_tools[call_id] = name

    def _tool_name(self, msg: ToolMessage) -> str:
        if msg.name:
            return msg.name
        return self._pending_tools.get(msg.tool_call_id or "", "tool")

    def print_turn_header(self, query: str) -> None:
        click.echo()
        click.echo(
            click.style("Zeno", bold=True, fg="cyan")
            + click.style(" › ", dim=True)
            + query
        )
        click.echo(
            click.style("─" * min(72, max(len(query) + 6, 40)), dim=True)
        )

    def print_node(self, node_name: str) -> None:
        if self.verbose:
            label = _NODE_LABELS.get(node_name, node_name)
            click.echo(click.style(f"[{label}]", dim=True))

    def print_message(self, msg: BaseMessage) -> None:
        if isinstance(msg, AIMessage):
            self._print_ai_message(msg)
        elif isinstance(msg, ToolMessage):
            self._print_tool_message(msg)
        elif isinstance(msg, HumanMessage) and self.verbose:
            click.echo(
                click.style("user: ", fg="blue") + format_message_content(msg)
            )

    def _print_ai_message(self, msg: AIMessage) -> None:
        self.register_tool_calls(msg)
        body = format_message_content(msg)
        if body:
            if self.verbose:
                click.echo(
                    click.style("assistant: ", fg="cyan", bold=True) + body
                )
            else:
                click.echo()
                click.echo(click.style("Answer", bold=True))
                click.echo()
                for line in body.splitlines():
                    click.echo(line)
        for tool_call in msg.tool_calls or []:
            name = tool_call.get("name", "?")
            args = tool_call.get("args") or {}
            if self.verbose:
                click.echo(
                    click.style("tool call: ", fg="yellow")
                    + f"{name}({_format_tool_args(args)})"
                )
            else:
                action = format_tool_action(name, args)
                click.echo("  " + click.style("→ ", fg="yellow") + action)

    def _print_tool_message(self, msg: ToolMessage) -> None:
        name = self._tool_name(msg)
        content = str(msg.content)
        if self.verbose:
            if len(content) > 500:
                content = content[:497] + "..."
            click.echo(click.style("tool result: ", fg="green") + content)
        else:
            summary = format_tool_outcome(name, content)
            for line in summary.splitlines():
                click.echo("      " + click.style(line, fg="green", dim=True))

    def print_state_extras(self, node_update: dict) -> None:
        if self.verbose:
            for key in STATE_KEYS:
                value = node_update.get(key)
                if value:
                    click.echo(
                        click.style(f"  [{key}] ", dim=True)
                        + _format_tool_args(value, 120)
                    )
            return
        lines: list[str] = []
        for key in STATE_KEYS:
            line = format_state_line(key, node_update.get(key))
            if line and line not in lines:
                lines.append(line)
        for line in lines:
            click.echo("      " + click.style(line, dim=True))

    def print_custom_event(self, payload: Any) -> None:
        """Render a stream_writer custom event.

        `context` events come from SessionContextMiddleware; `progress`
        events come from subagents (geocoder, dataset selector).
        """
        if not isinstance(payload, dict):
            return
        etype = payload.get("type")
        if etype == "context":
            self.print_session_block(
                payload.get("session_block", ""),
                payload.get("message_count", 0),
            )
        elif etype == "progress":
            self.print_progress(payload)

    def print_progress(self, payload: dict) -> None:
        """Render a subagent progress step (LLM call, DB lookup, shortlist)."""
        message = payload.get("message")
        if not message:
            return
        if self.verbose:
            tag = f"{payload.get('subagent', '?')}/{payload.get('stage', '?')}"
            message = f"{message}  [{tag}]"
        click.echo("      " + click.style(f"· {message}", fg="blue", dim=True))

    def print_session_block(self, block: str, message_count: int) -> None:
        """Print the live session-state snapshot SessionContextMiddleware
        prepends before each model call. Skipped when unchanged so it shows
        only as the AOI / dataset / date range / insight actually evolve.
        """
        block = block.strip()
        if not block or block == self._last_session_block:
            return
        self._last_session_block = block
        click.echo()
        for i, line in enumerate(block.splitlines()):
            if i == 0 and self.verbose:
                line = f"{line}  ({message_count} messages)"
            click.echo("  " + click.style(f"│ {line}", fg="magenta", dim=True))

    def print_data_table(
        self, label: str, data: Any, *, max_rows: int = DATA_HEAD_ROWS
    ) -> None:
        """Render the head of a data block (rows or column-oriented dict)."""
        import pandas as pd

        rows = data
        # Some payloads wrap the rows in a single {"data": ...} envelope.
        if isinstance(rows, dict) and set(rows.keys()) == {"data"}:
            rows = rows["data"]
        try:
            df = pd.DataFrame(rows)
        except Exception:
            return
        if df.empty:
            return
        total = len(df)
        click.echo()
        click.echo(
            "      "
            + click.style(
                f"{label} — {total} row(s) × {len(df.columns)} col(s)",
                dim=True,
            )
        )
        with pd.option_context(
            "display.max_colwidth", 32, "display.width", 120
        ):
            rendered = df.head(max_rows).to_string(index=False, max_cols=8)
        for line in rendered.splitlines():
            click.echo("      " + click.style(line, fg="cyan", dim=True))
        if total > max_rows:
            click.echo(
                "      "
                + click.style(f"… {total - max_rows} more row(s)", dim=True)
            )

    def print_chart_data(
        self, charts_data: Any, *, max_rows: int = DATA_HEAD_ROWS
    ) -> None:
        """Render the head of each generated chart's data."""
        if not isinstance(charts_data, list):
            return
        for chart in charts_data:
            if not isinstance(chart, dict):
                continue
            title = chart.get("title") or chart.get("id") or "chart"
            ctype = chart.get("type") or "?"
            self.print_data_table(
                f"Chart: {title} [{ctype}]",
                chart.get("data"),
                max_rows=max_rows,
            )


async def _render_pulled_data(
    printer: _CliPrinter,
    statistics: Any,
    *,
    max_rows: int = DATA_HEAD_ROWS,
) -> None:
    """Render the head of each pulled-data statistic.

    Pulled statistics keep `data` empty in state to stay light; the rows
    live behind `source_url`, so fetch them for display.
    """
    if not isinstance(statistics, list):
        return
    for stat in statistics:
        if not isinstance(stat, dict):
            continue
        rows = stat.get("data") or None
        url = stat.get("source_url")
        if not rows and url:
            try:
                rows = await fetch_statistics_from_url(url)
            except Exception as exc:  # noqa: BLE001
                click.echo(
                    "      "
                    + click.style(
                        f"(could not fetch pulled data: {exc})", dim=True
                    )
                )
                continue
        if rows:
            printer.print_data_table(
                f"Pulled: {stat.get('dataset_name', 'data')}",
                rows,
                max_rows=max_rows,
            )


def _collect_messages(node_update: dict) -> list[BaseMessage]:
    messages = node_update.get("messages", [])
    return [m for m in messages if isinstance(m, BaseMessage)]


async def _stream_turn(
    agent,
    input_state: dict,
    config: dict,
    *,
    printer: _CliPrinter,
) -> list[BaseMessage]:
    new_messages: list[BaseMessage] = []
    # stream_mode is a list, so each item is a (mode, payload) tuple:
    #   "updates" → {node_name: node_update}
    #   "custom"  → dict passed to stream_writer (session-context block)
    async for mode, payload in agent.astream(
        input_state,
        config=config,
        stream_mode=["updates", "custom"],
        subgraphs=False,
    ):
        if mode == "custom":
            printer.print_custom_event(payload)
            continue
        for node_name, node_update in payload.items():
            printer.print_node(node_name)
            for msg in _collect_messages(node_update):
                printer.print_message(msg)
                new_messages.append(msg)
            printer.print_state_extras(node_update)
            if isinstance(node_update, dict):
                if node_update.get("statistics"):
                    await _render_pulled_data(
                        printer, node_update["statistics"]
                    )
                if node_update.get("charts_data"):
                    printer.print_chart_data(node_update["charts_data"])
    return new_messages


async def _run_query(
    agent,
    query: str,
    *,
    thread_id: str,
    is_checkpointed: bool,
    message_history: list[BaseMessage],
    printer: _CliPrinter,
    show_header: bool,
) -> None:
    if show_header:
        printer.print_turn_header(query)

    if is_checkpointed:
        # The checkpointer restores prior messages and graph state for the
        # thread, so only the new message is sent.
        config = {"configurable": {"thread_id": thread_id}}
        input_state = {"messages": [HumanMessage(content=query)]}
    else:
        config = {}
        message_history.append(HumanMessage(content=query))
        input_state = {"messages": message_history}

    new_messages = await _stream_turn(
        agent, input_state, config, printer=printer
    )

    if not is_checkpointed:
        message_history.extend(new_messages)


async def _ensure_user_exists(user_id: str, email: str) -> None:
    """Ensure user_id exists in users table (required for statistics FK)."""
    async with get_session_from_pool() as session:
        result = await session.execute(
            select(UserOrm).where(UserOrm.id == user_id)
        )
        if result.scalars().first() is not None:
            return
        session.add(
            UserOrm(
                id=user_id,
                name="CLI User",
                email=email,
            )
        )
        await session.commit()


async def _fetch_agent(
    system_prompt: Optional[str],
    *,
    use_postgres: bool,
    use_memory: bool,
):
    if use_postgres:
        return await fetch_zeno(system_prompt=system_prompt)
    checkpointer = InMemorySaver() if use_memory else None
    return await fetch_zeno_anonymous(
        system_prompt=system_prompt, checkpointer=checkpointer
    )


async def _interactive_loop(
    agent,
    *,
    thread_id: str,
    is_checkpointed: bool,
    checkpoint_kind: str,
    using_custom_prompt: bool,
    printer: _CliPrinter,
) -> None:
    click.echo(
        click.style("Zeno agent CLI", bold=True)
        + " — enter a message (Ctrl-D or /quit to exit)"
    )
    if using_custom_prompt:
        click.echo(click.style("Using custom system prompt.", dim=True))
    if is_checkpointed:
        click.echo(
            click.style(f"Thread: {thread_id} ({checkpoint_kind})", dim=True)
        )

    message_history: list[BaseMessage] = []
    while True:
        try:
            click.echo()
            line = click.prompt("you", prompt_suffix="> ")
        except (EOFError, KeyboardInterrupt):
            click.echo()
            break

        stripped = line.strip()
        if not stripped:
            continue
        if stripped.lower() in {"/quit", "/exit", "/q"}:
            break

        await _run_query(
            agent,
            stripped,
            thread_id=thread_id,
            is_checkpointed=is_checkpointed,
            message_history=message_history,
            printer=printer,
            show_header=True,
        )


async def _async_main(
    query: Optional[str],
    interactive: bool,
    system_prompt: Optional[str],
    thread_id: str,
    use_checkpoint: bool,
    user_id: str,
    user_email: str,
    verbose: bool,
) -> None:
    structlog.contextvars.clear_contextvars()
    bind_request_logging_context(user_id=user_id, thread_id=thread_id)

    printer = _CliPrinter(verbose=verbose)

    is_interactive = interactive or not query
    # --checkpoint selects the durable Postgres checkpointer. Otherwise
    # interactive mode still gets an in-memory checkpointer so AOI / dataset
    # / pulled-data state carries across turns; a single -q run stays
    # stateless (one turn needs no checkpoint).
    use_postgres = use_checkpoint
    use_memory = is_interactive and not use_checkpoint
    is_checkpointed = use_postgres or use_memory
    checkpoint_kind = "Postgres" if use_postgres else "in-memory"

    with cli_logging(quiet=not verbose):
        await initialize_global_pool()
        await _ensure_user_exists(user_id, user_email)
        if use_postgres:
            await get_checkpointer_pool()

        agent = await _fetch_agent(
            system_prompt, use_postgres=use_postgres, use_memory=use_memory
        )
        try:
            if is_interactive:
                await _interactive_loop(
                    agent,
                    thread_id=thread_id,
                    is_checkpointed=is_checkpointed,
                    checkpoint_kind=checkpoint_kind,
                    using_custom_prompt=system_prompt is not None,
                    printer=printer,
                )
            else:
                await _run_query(
                    agent,
                    query,
                    thread_id=thread_id,
                    is_checkpointed=is_checkpointed,
                    message_history=[],
                    printer=printer,
                    show_header=True,
                )
        finally:
            await close_global_pool()
            if use_postgres:
                await close_checkpointer_pool()


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "-q",
    "--query",
    help="Single user message to send to the agent.",
)
@click.option(
    "-i",
    "--interactive",
    is_flag=True,
    help="Multi-turn REPL (default when --query is omitted).",
)
@click.option(
    "-p",
    "--prompt",
    help="Override the agent system prompt (for prompt experiments).",
)
@click.option(
    "-f",
    "--prompt-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Read system prompt from a file.",
)
@click.option(
    "--show-prompt",
    is_flag=True,
    help="Print the default system prompt and exit.",
)
@click.option(
    "--thread-id",
    default=None,
    help="Thread id for checkpointed runs (default: random uuid).",
)
@click.option(
    "--checkpoint",
    is_flag=True,
    help=(
        "Persist conversation durably in Postgres (requires DATABASE_URL). "
        "Interactive mode otherwise keeps state in an in-memory checkpointer."
    ),
)
@click.option(
    "--user-id",
    default=DEFAULT_CLI_USER_ID,
    show_default=True,
    help="User id for tools that query per-user data (e.g. custom areas).",
)
@click.option(
    "--user-email",
    default=None,
    help="Email for the CLI user row (default: <user-id>@cli.local).",
)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="Show structlog output, node names, and full tool payloads.",
)
def main(
    query: Optional[str],
    interactive: bool,
    prompt: Optional[str],
    prompt_file: Optional[Path],
    show_prompt: bool,
    thread_id: Optional[str],
    checkpoint: bool,
    user_id: str,
    user_email: str,
    verbose: bool,
) -> None:
    """Run the Zeno geospatial agent locally."""
    if show_prompt:
        click.echo(get_prompt())
        return

    if prompt and prompt_file:
        raise click.UsageError("Use only one of --prompt or --prompt-file.")

    system_prompt = _resolve_system_prompt(prompt, prompt_file)
    resolved_thread_id = thread_id or str(uuid.uuid4())
    resolved_user_email = user_email or f"{user_id}@cli.local"

    try:
        asyncio.run(
            _async_main(
                query=query,
                interactive=interactive,
                system_prompt=system_prompt,
                thread_id=resolved_thread_id,
                use_checkpoint=checkpoint,
                user_id=user_id,
                user_email=resolved_user_email,
                verbose=verbose,
            )
        )
    except KeyboardInterrupt:
        click.echo("\nInterrupted.", err=True)
        sys.exit(130)


def _resolve_system_prompt(
    prompt: Optional[str],
    prompt_file: Optional[Path],
) -> Optional[str]:
    if prompt_file is not None:
        return prompt_file.read_text(encoding="utf-8").strip()
    if prompt is not None:
        return prompt.strip()
    return None


if __name__ == "__main__":
    main()
