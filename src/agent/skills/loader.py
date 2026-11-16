import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.agent.skills.capabilities import render_capabilities_body
from src.agent.tool_spec import bound_availability

_SKILLS_DIR = Path(__file__).resolve().parent / "skills_md"


@dataclass
class SkillMeta:
    name: str
    description: str
    when_to_use: str
    body: str
    # Tools the skill's workflow requires; the skill is only advertised in a
    # profile that binds all of them. Empty for informational skills.
    requires: tuple[str, ...] = ()


def _parse(path: Path) -> SkillMeta | None:
    text = path.read_text()
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    front = parts[1]
    body = parts[2].lstrip("\n")
    meta: dict[str, str] = {}
    for line in front.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        meta[k.strip()] = v.strip()
    name = meta.get("name") or path.stem
    requires = tuple(
        t.strip() for t in meta.get("requires", "").split(",") if t.strip()
    )
    return SkillMeta(
        name=name,
        description=meta.get("description", ""),
        when_to_use=meta.get("when_to_use", ""),
        body=body,
        requires=requires,
    )


def load_skills() -> list[SkillMeta]:
    skills: list[SkillMeta] = []
    if not _SKILLS_DIR.exists():
        return skills
    for path in sorted(_SKILLS_DIR.glob("*.md")):
        s = _parse(path)
        if s is not None:
            skills.append(s)
    return skills


_SKILLS: dict[str, SkillMeta] = {s.name: s for s in load_skills()}


def get_skill(name: str) -> SkillMeta | None:
    return _SKILLS.get(name)


# A flagged block of a skill body: the lines between
# "<!-- flag: NAME -->" (or "<!-- no flag: NAME -->") and "<!-- end flag -->",
# each marker on a line of its own. A profile with the flag NAME
# (AgentConfig.flags) reads the "flag" blocks; a profile without it reads
# the "no flag" blocks. The marker lines are never shown. No nesting.
_FLAG_START = re.compile(r"^<!-- (no )?flag: ([a-z0-9-]+) -->$")
_FLAG_END = "<!-- end flag -->"


def flag_names(body: str) -> set[str]:
    """The flags that the blocks of a skill body name."""
    return {
        match.group(2)
        for line in body.splitlines()
        if (match := _FLAG_START.match(line.strip()))
    }


def apply_flags(body: str, flags: frozenset[str]) -> str:
    """The body with the flagged blocks that `flags` selects, and without
    the marker lines."""
    kept: list[str] = []
    keep = True
    in_block = False
    for line in body.splitlines(keepends=True):
        stripped = line.strip()
        match = _FLAG_START.match(stripped)
        if match:
            if in_block:
                raise ValueError(f"Nested flag block: {stripped}")
            in_block = True
            negated, name = match.group(1) is not None, match.group(2)
            keep = (name in flags) != negated
            continue
        if stripped == _FLAG_END:
            if not in_block:
                raise ValueError("Flag block end without a start")
            in_block, keep = False, True
            continue
        if keep:
            kept.append(line)
    if in_block:
        raise ValueError("Flag block without an end")
    return "".join(kept)


def render_body(
    skill: SkillMeta, flags: Optional[frozenset[str]] = None
) -> str:
    """A skill's body as handed to the model (capabilities is templated).
    `flags` selects the flagged blocks; by default the flags of the
    current request's profile."""
    if flags is None:
        flags = bound_availability().flags
    body = apply_flags(skill.body, flags)
    if skill.name == "capabilities":
        return render_capabilities_body(body)
    return body


def get_skill_body(name: str) -> str | None:
    s = _SKILLS.get(name)
    return None if s is None else render_body(s)


def all_skills() -> list[SkillMeta]:
    return list(_SKILLS.values())
