#!/usr/bin/env python3
"""Static prompt size report: what the agent sends before the user types.

    uv run python scripts/prompt_size.py [--json] [--write-snapshot PATH]

For each agent profile in ``default_registry`` it prints characters and
estimated tokens for:

- the system prompt (``get_prompt(cfg)``),
- the bound tool schemas (``cfg.bound_tools()`` through
  ``convert_to_openai_tool``), each tool and the total, and the part that
  the profile leaves out of a model call until a skill is read,
- the fixed cost of a model call: the system prompt plus the schemas that
  are sent before any skill is read,
- each skill body (what ``read_skill`` returns),
- each dataset's model-instruction fields in the catalog.

It calls no API and no model. The token figure is an ESTIMATE: characters
divided by 4, rounded up. It is not a real tokenizer count. A real tokenizer
needs a vocabulary file that ``tiktoken`` downloads on first use, so its
result would depend on the network and on a cache. The estimate is stable
and good enough to compare two versions of the same prompt.

``--write-snapshot PATH`` writes the character counts that
``tests/unit/agent/test_prompt_size.py`` compares against. Run it after a
prompt change that is meant to change the size, and commit the file.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Catalog fields that a model reads. The context layer descriptions are
# summed under one key. `function_usage_notes` is also sent to the
# orchestrator by pick_dataset, so it is counted with the others.
DATASET_TEXT_FIELDS = (
    "prompt_instructions",
    "code_instructions",
    "presentation_instructions",
    "selection_hints",
    "cautions",
    "function_usage_notes",
)
CONTEXT_LAYERS_KEY = "context_layer_descriptions"
CHARS_PER_TOKEN = 4

SNAPSHOT_PATH = (
    REPO_ROOT / "tests" / "unit" / "agent" / "prompt_size_snapshot.json"
)


def estimate_tokens(chars: int) -> int:
    """Deterministic, offline estimate: ``ceil(chars / 4)``."""
    return -(-chars // CHARS_PER_TOKEN)


def _size(chars: int) -> dict:
    return {"chars": chars, "est_tokens": estimate_tokens(chars)}


def tool_schema_chars(tool) -> int:
    from langchain_core.utils.function_calling import convert_to_openai_tool

    return len(json.dumps(convert_to_openai_tool(tool), ensure_ascii=False))


def deferred_tool_names(cfg) -> frozenset[str]:
    """The bound tools that a profile leaves out of a model call until a
    skill is read (DeferredToolsMiddleware); empty for most profiles."""
    from src.agent.agent_config import CONCISE_REPLIES, DEFERRED_SKILL_TOOLS

    if CONCISE_REPLIES not in cfg.flags:
        return frozenset()
    names = cfg.tool_names()
    return frozenset(
        tool
        for skill, tools in DEFERRED_SKILL_TOOLS.items()
        if cfg.availability().has_skill(skill)
        for tool in tools
        if tool in names
    )


def profile_sizes() -> dict:
    from src.agent.agent_config import default_registry
    from src.agent.graph import get_prompt

    profiles = {}
    for cfg in default_registry.configs():
        tools = {t.name: tool_schema_chars(t) for t in cfg.bound_tools()}
        deferred = deferred_tool_names(cfg)
        profiles[cfg.name] = {
            "system_prompt": len(get_prompt(cfg)),
            "tools": tools,
            "tools_total": sum(tools.values()),
            "tools_deferred": sum(
                c for t, c in tools.items() if t in deferred
            ),
        }
    return profiles


def skill_sizes() -> dict[str, int]:
    from src.agent.skills import all_skills, get_skill_body

    return {s.name: len(get_skill_body(s.name) or "") for s in all_skills()}


def dataset_sizes() -> dict[str, dict[str, int]]:
    from src.agent.datasets.config import DATASETS

    sizes: dict[str, dict[str, int]] = {}
    for record in DATASETS:
        fields = {
            f: len(str(record[f]))
            for f in DATASET_TEXT_FIELDS
            if record.get(f)
        }
        layers = sum(
            len(str(layer.get("description") or ""))
            for layer in record.get("context_layers") or []
        )
        if layers:
            fields[CONTEXT_LAYERS_KEY] = layers
        sizes[record["dataset_name"]] = fields
    return sizes


def collect() -> dict:
    """All sizes as characters. This is the snapshot shape."""
    return {
        "profiles": profile_sizes(),
        "skills": skill_sizes(),
        "datasets": dataset_sizes(),
    }


def with_tokens(data: dict) -> dict:
    """The same data with an estimated token count next to every figure."""
    profiles = {}
    for name, p in data["profiles"].items():
        profiles[name] = {
            "system_prompt": _size(p["system_prompt"]),
            "tools": {t: _size(c) for t, c in p["tools"].items()},
            "tools_total": _size(p["tools_total"]),
            "tools_deferred": _size(p["tools_deferred"]),
            "fixed_per_call": _size(
                p["system_prompt"] + p["tools_total"] - p["tools_deferred"]
            ),
        }
    datasets = {}
    for name, fields in data["datasets"].items():
        datasets[name] = {
            **{f: _size(c) for f, c in fields.items()},
            "total": _size(sum(fields.values())),
        }
    return {
        "token_estimate": f"ceil(chars / {CHARS_PER_TOKEN}); not a tokenizer count",
        "profiles": profiles,
        "skills": {n: _size(c) for n, c in data["skills"].items()},
        "datasets": datasets,
    }


def _row(label: str, size: dict, width: int = 44) -> str:
    return f"  {label:<{width}} {size['chars']:>9,} {size['est_tokens']:>8,}"


def render_text(data: dict) -> str:
    sized = with_tokens(data)
    head = f"  {'':<44} {'chars':>9} {'~tokens':>8}"
    lines = [f"Token figures are estimates: {sized['token_estimate']}."]
    for name, p in sized["profiles"].items():
        lines += ["", f"profile: {name}", head]
        lines.append(_row("system prompt", p["system_prompt"]))
        lines.append(_row("tool schemas, total", p["tools_total"]))
        if p["tools_deferred"]["chars"]:
            lines.append(
                _row("  of which deferred until a skill", p["tools_deferred"])
            )
        lines.append(
            _row("fixed cost of each model call", p["fixed_per_call"])
        )
        for tool, size in sorted(
            p["tools"].items(), key=lambda kv: -kv[1]["chars"]
        ):
            lines.append(_row(f"  tool {tool}", size))
    lines += ["", "skill bodies (after read_skill)", head]
    for name, size in sized["skills"].items():
        lines.append(_row(name, size))
    lines += ["", "dataset instruction fields", head]
    for name, fields in sized["datasets"].items():
        lines.append(_row(name, fields["total"]))
        for field, size in fields.items():
            if field != "total":
                lines.append(_row(f"  {field}", size))
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--json", action="store_true", help="print JSON, not text"
    )
    parser.add_argument(
        "--write-snapshot",
        nargs="?",
        const=str(SNAPSHOT_PATH),
        metavar="PATH",
        help=f"write the character snapshot (default {SNAPSHOT_PATH.relative_to(REPO_ROOT)})",
    )
    args = parser.parse_args()
    # Some imports print banners (NumExpr) to stdout; keep stdout clean for --json.
    with contextlib.redirect_stdout(sys.stderr):
        data = collect()
    if args.write_snapshot:
        Path(args.write_snapshot).write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"wrote {args.write_snapshot}", file=sys.stderr)
        return 0
    if args.json:
        print(json.dumps(with_tokens(data), indent=2, sort_keys=True))
    else:
        sys.stdout.write(render_text(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
