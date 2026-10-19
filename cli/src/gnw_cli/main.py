"""The `gnw` commands.

Each command calls a tool of the GNW MCP server and prints a short summary.
Rows never go to the terminal: `pull` and `charts` write them to files, by
running the pull.py the server returns, so the files on disk are exactly
what the script repeats.
"""

import argparse
import asyncio
import csv
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path

from fastmcp import Client

DEFAULT_SERVER = "https://api.globalnaturewatch.org/mcp"
DEFAULT_OUT = "gnw"
SKILL_URI = "skill://gnw-charting/"


class CliError(Exception):
    pass


def _server(args) -> str:
    return args.server or os.getenv("GNW_MCP_URL") or DEFAULT_SERVER


async def _call(client: Client, tool: str, arguments: dict):
    result = await client.call_tool(tool, arguments, raise_on_error=False)
    if result.is_error:
        raise CliError(_text(result) or f"{tool} failed.")
    return result


def _text(result) -> str:
    return "\n".join(
        part.text for part in result.content if getattr(part, "text", None)
    ).strip()


def _print_json(value) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


# ---- Pulls -------------------------------------------------------------------


def _pull_arguments(args) -> dict:
    arguments = {"aoi_ids": args.aoi, "dataset_id": args.dataset}
    for name in ("start_date", "end_date", "context_layer", "canopy_cover"):
        if getattr(args, name) is not None:
            arguments[name] = getattr(args, name)
    if args.change_over_time:
        arguments["change_over_time"] = True
    return arguments


def _write_pull(structured: dict, out: Path) -> Path:
    """Write the pull's folder by running its pull.py, and return it."""
    script = structured.get("script")
    if not script:
        raise CliError(
            "The server returned no pull.py for this pull, so it cannot be "
            "written to files."
        )
    folder = out / "pulls" / (structured.get("result_id") or "latest")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "pull.py"
    path.write_text(script, encoding="utf-8")
    run = subprocess.run(
        [sys.executable, "-I", str(path), str(folder)],
        capture_output=True,
        text=True,
    )
    if run.returncode != 0:
        raise CliError(f"pull.py failed:\n{run.stderr.strip()}")
    # pull.py warns when the rows differ from the server's.
    if run.stderr.strip():
        print(run.stderr.strip(), file=sys.stderr)
    return folder


def _record(out: Path, entry: dict) -> None:
    """Add a command to gnw/manifest.json: what made each folder."""
    path = out / "manifest.json"
    manifest = (
        json.loads(path.read_text(encoding="utf-8"))
        if path.exists()
        else {"entries": []}
    )
    manifest["entries"].append(
        {
            "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **entry,
        }
    )
    out.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _provenance(structured: dict) -> dict:
    return {
        key: value
        for key, value in structured.items()
        if key not in ("rows", "charts", "script")
    }


def _columns(folder: Path) -> list[str]:
    with open(folder / "rows.csv", encoding="utf-8") as file:
        return next(csv.reader(file), [])


def _summary(result, folder: Path, structured: dict) -> list[str]:
    """The tool's heading and notes, without the rows, and the files."""
    lines = _text(result).splitlines()
    kept = [lines[0]] if lines else []
    kept += [
        line
        for line in lines[1:]
        if line.startswith(("The date range was fitted", "Citation:"))
    ]
    kept.append(
        f"Rows: {folder / 'rows.csv'} ({structured['row_count']} rows)"
    )
    kept.append(f"Columns: {', '.join(_columns(folder))}")
    kept.append(f"Repeat: python {folder / 'pull.py'} {folder}")
    return kept


async def pull(args, server) -> None:
    out = Path(args.out)
    async with Client(server) as client:
        result = await _call(client, "pull_data", _pull_arguments(args))
    structured = result.structured_content
    folder = _write_pull(structured, out)
    _record(
        out,
        {
            "command": "pull",
            "arguments": _pull_arguments(args),
            "folder": str(folder),
            "result_id": structured.get("result_id"),
            "rows_sha256": structured.get("rows_sha256"),
        },
    )
    if args.json:
        _print_json({**_provenance(structured), "folder": str(folder)})
    else:
        print("\n".join(_summary(result, folder, structured)))


async def charts(args, server) -> None:
    out = Path(args.out)
    async with Client(server) as client:
        result = await _call(client, "curated_charts", _pull_arguments(args))
    structured = result.structured_content
    folder = _write_pull(structured, out)
    charts_path = folder / "charts.json"
    charts_path.write_text(
        json.dumps(
            {
                "generator": structured.get("generator"),
                "charts": structured.get("charts", []),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    _record(
        out,
        {
            "command": "charts",
            "arguments": _pull_arguments(args),
            "folder": str(folder),
            "result_id": structured.get("result_id"),
            "rows_sha256": structured.get("rows_sha256"),
        },
    )
    if args.json:
        _print_json({**_provenance(structured), "folder": str(folder)})
        return
    generator = structured.get("generator") or {}
    print(f"GNW's curated charts ({generator.get('name')}):")
    for chart in structured.get("charts", []):
        print(
            f"  {chart['position'] + 1}. {chart['title']} ({chart['chart_type']})"
        )
    print(f"Specs: {charts_path}")
    print(f"Rows: {folder / 'rows.csv'}")
    print(f"Code: {generator.get('code_url')}")


def replay(args) -> None:
    """Run every pull.py under gnw/pulls again; report the ones whose rows
    changed."""
    scripts = sorted(Path(args.out).glob("pulls/*/pull.py"))
    if not scripts:
        raise CliError(f"No pulls under {Path(args.out) / 'pulls'}.")
    changed = 0
    for script in scripts:
        run = subprocess.run(
            [sys.executable, "-I", str(script), str(script.parent)],
            capture_output=True,
            text=True,
        )
        if run.returncode != 0:
            changed += 1
            print(f"FAILED {script.parent}: {run.stderr.strip()}")
        elif run.stderr.strip():
            changed += 1
            print(f"CHANGED {script.parent}: {run.stderr.strip()}")
        else:
            print(f"same    {script.parent}")
    if changed:
        raise CliError(f"{changed} of {len(scripts)} pulls did not repeat.")


# ---- Catalog and areas -------------------------------------------------------


async def datasets(args, server) -> None:
    async with Client(server) as client:
        if args.dataset_id is None:
            result = await _call(client, "list_datasets", {})
        else:
            result = await _call(
                client, "get_dataset", {"dataset_id": args.dataset_id}
            )
    if args.json:
        _print_json(result.structured_content)
    else:
        print(_text(result))


async def areas(args, server) -> None:
    arguments: dict = {"name": args.name, "limit": args.limit}
    if args.source:
        arguments["sources"] = args.source
    async with Client(server) as client:
        result = await _call(client, "search_areas", arguments)
    if args.json:
        _print_json(result.structured_content)
    else:
        print(_text(result))


async def chart_code(args, server) -> None:
    async with Client(server) as client:
        result = await _call(
            client, "get_chart_code", {"dataset_id": args.dataset_id}
        )
    print(result.structured_content["source"])


# ---- Skills ------------------------------------------------------------------


async def skill_install(args, server) -> None:
    """Write the gnw-charting skill (from the server) and the gnw-cli skill
    (shipped with this package) into a skills folder."""
    target = Path(args.dir)
    written = []
    async with Client(server) as client:
        for resource in await client.list_resources():
            uri = str(resource.uri)
            if not uri.startswith(SKILL_URI) or uri.endswith("/_manifest"):
                continue
            [content] = await client.read_resource(uri)
            path = target / "gnw-charting" / uri.removeprefix(SKILL_URI)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content.text, encoding="utf-8")
            written.append(path)
    cli_skill = resources.files("gnw_cli") / "skill" / "SKILL.md"
    path = target / "gnw-cli" / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cli_skill.read_text(encoding="utf-8"), encoding="utf-8")
    written.append(path)
    print(
        f"Wrote {len(written)} files to {target}/gnw-charting and {target}/gnw-cli."
    )


# ---- Arguments ---------------------------------------------------------------


def _add_pull_arguments(parser) -> None:
    parser.add_argument(
        "--aoi",
        action="append",
        required=True,
        help="An area id from `gnw areas`, e.g. gadm:BRA.14_1. Repeat to compare areas.",
    )
    parser.add_argument(
        "--dataset",
        type=int,
        required=True,
        help="A dataset id from `gnw datasets`.",
    )
    parser.add_argument(
        "--start", dest="start_date", help="First day, YYYY-MM-DD."
    )
    parser.add_argument("--end", dest="end_date", help="Last day, YYYY-MM-DD.")
    parser.add_argument(
        "--context-layer", help="A context layer of the dataset."
    )
    parser.add_argument(
        "--canopy-cover", type=int, help="Minimum canopy cover, percent."
    )
    parser.add_argument(
        "--change-over-time",
        action="store_true",
        help="Land cover only: the class transitions between the two years.",
    )


def build_parser() -> argparse.ArgumentParser:
    # The options every command takes, after its name.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--server",
        help=f"The GNW MCP server URL (default: $GNW_MCP_URL or {DEFAULT_SERVER}).",
    )
    common.add_argument(
        "--out",
        default=DEFAULT_OUT,
        help="The folder pulls go to (default: gnw).",
    )
    common.add_argument(
        "--json", action="store_true", help="Print JSON instead of a summary."
    )
    parser = argparse.ArgumentParser(
        prog="gnw",
        description=(
            "Global Nature Watch data as files: pulls land in "
            "<out>/pulls/<result_id>/ with the rows, the request, the "
            "provenance and the pull.py that repeats them."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    def command(name, help):
        return commands.add_parser(name, help=help, parents=[common])

    found = command("areas", "Find area ids by name.")
    found.add_argument("name", help="'Place' or 'Place, Parent', in English.")
    found.add_argument(
        "--source",
        action="append",
        choices=["gadm", "kba", "wdpa", "landmark"],
        help="Limit to a source. Repeat for several.",
    )
    found.add_argument("--limit", type=int, default=10)

    listed = command(
        "datasets",
        "List the datasets, or show one with its options and cautions.",
    )
    listed.add_argument("dataset_id", type=int, nargs="?")

    pulled = command("pull", "Pull statistics into files.")
    _add_pull_arguments(pulled)

    charted = command(
        "charts", "Pull, and write GNW's curated charts to charts.json."
    )
    _add_pull_arguments(charted)

    code = command("chart-code", "Print a dataset's chart generator.")
    code.add_argument("dataset_id", type=int)

    command(
        "replay",
        "Run every pull.py again and report pulls whose rows changed.",
    )

    skill = commands.add_parser("skill", help="Install the agent skills.")
    skill_commands = skill.add_subparsers(dest="skill_command", required=True)
    install = skill_commands.add_parser(
        "install", help="Write the skills to a folder.", parents=[common]
    )
    install.add_argument(
        "--dir",
        default=".claude/skills",
        help="The skills folder (default: .claude/skills; .gemini/skills for Gemini CLI).",
    )
    return parser


COMMANDS = {
    "areas": areas,
    "datasets": datasets,
    "pull": pull,
    "charts": charts,
    "chart-code": chart_code,
}


def main(argv=None, server=None) -> None:
    """Run a command. `server` overrides the URL with a server object, for
    tests."""
    args = build_parser().parse_args(argv)
    server = server or _server(args)
    try:
        if args.command == "replay":
            replay(args)
        elif args.command == "skill":
            asyncio.run(skill_install(args, server))
        else:
            asyncio.run(COMMANDS[args.command](args, server))
    except CliError as error:
        print(f"gnw: {error}", file=sys.stderr)
        sys.exit(1)
