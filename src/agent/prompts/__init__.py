"""The orchestrator system prompt as numbered markdown sections.

Used by the profiles with the ``concise-replies`` flag
(docs/concise-agent-plan.md, iteration 2). Each file in ``sections/`` is one
section; ``build_prompt`` joins them in file-name order and adds the parts
that depend on the profile: the skills list and the current surface.

A block of a section that names a skill or a tool is kept only when the
profile can serve it. The block is the lines between
``<!-- tool: NAME -->`` (or ``<!-- skill: NAME -->``) and ``<!-- end -->``,
each marker on a line of its own. The marker lines are never shown. No
nesting.

The prompt holds only the rules that cross tools (order, stop conditions,
terminal tools). What one tool does is in its description (the tool
schema), not here.
"""

import re
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

from src.agent.tool_spec import Availability

SECTIONS_DIR = Path(__file__).resolve().parent / "sections"

_GATE_START = re.compile(r"^<!-- (tool|skill): ([a-z0-9_-]+) -->$")
_GATE_END = "<!-- end -->"


@lru_cache(maxsize=None)
def section_texts() -> tuple[tuple[str, str], ...]:
    """(file name, text) of each section, in file-name order."""
    return tuple(
        (path.name, path.read_text(encoding="utf-8"))
        for path in sorted(SECTIONS_DIR.glob("*.md"))
    )


def gates(text: str) -> set[tuple[str, str]]:
    """The (kind, name) pairs that the gated blocks of ``text`` name."""
    return {
        (match.group(1), match.group(2))
        for line in text.splitlines()
        if (match := _GATE_START.match(line.strip()))
    }


def apply_gates(text: str, available: Availability) -> str:
    """``text`` without the gated blocks that ``available`` cannot serve,
    and without the marker lines."""
    kept: list[str] = []
    keep = True
    in_block = False
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        match = _GATE_START.match(stripped)
        if match:
            if in_block:
                raise ValueError(f"Nested gate block: {stripped}")
            in_block = True
            keep = available.allows((match.group(1), match.group(2)))  # type: ignore[arg-type]
            continue
        if stripped == _GATE_END:
            if not in_block:
                raise ValueError("Gate block end without a start")
            in_block, keep = False, True
            continue
        if keep:
            kept.append(line)
    if in_block:
        raise ValueError("Gate block without an end")
    return "".join(kept)


def skills_section(skill_lines: Iterable[str], number: int) -> str:
    """The skills list, or an empty string for a profile with no skills
    (it binds no ``read_skill``)."""
    lines = list(skill_lines)
    if not lines:
        return ""
    return (
        f"# {number}. Skills\n\n"
        "A skill is a workflow for one kind of request. When a skill "
        "below matches the request, call `read_skill(name)` one time and "
        "follow it. Usually one skill applies.\n\n" + "\n".join(lines)
    )


def build_prompt(
    available: Availability,
    skill_lines: Iterable[str],
    surface: Optional[str] = None,
) -> str:
    """Join the sections, the skills list and the current surface."""
    parts = [
        apply_gates(text, available).strip() for _, text in section_texts()
    ]
    skills = skills_section(skill_lines, len(parts) + 1)
    if skills:
        parts.append(skills)
    if surface:
        parts.append(f"# {len(parts) + 1}. Current surface\n\n{surface}")
    return "\n\n".join(parts) + "\n"
