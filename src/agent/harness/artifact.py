import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


def _new_id() -> str:
    return f"art_{uuid.uuid4().hex[:12]}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Artifact:
    type: str
    title: str
    content: dict
    query: str = ""
    inputs: dict = field(default_factory=dict)
    code: list[dict] = field(default_factory=list)
    follow_ups: list[str] = field(default_factory=list)
    parent_id: str | None = None
    id: str = field(default_factory=_new_id)
    created_at: datetime = field(default_factory=_now)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["created_at"] = self.created_at.isoformat()
        return d
