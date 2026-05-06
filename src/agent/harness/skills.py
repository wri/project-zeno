from dataclasses import dataclass
from pathlib import Path

_SKILLS_DIR = Path(__file__).resolve().parent / "skills_md"


@dataclass
class SkillMeta:
    name: str
    description: str
    when_to_use: str
    body: str


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
    return SkillMeta(
        name=name,
        description=meta.get("description", ""),
        when_to_use=meta.get("when_to_use", ""),
        body=body,
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


def get_skill_body(name: str) -> str | None:
    s = _SKILLS.get(name)
    return s.body if s else None


def all_skills() -> list[SkillMeta]:
    return list(_SKILLS.values())
