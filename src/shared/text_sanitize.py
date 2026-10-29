"""Strip characters that must never be stored from LLM-written text.

Postgres rejects NUL (``\\x00``) in ``text`` columns and ``\\u0000`` in JSONB,
which fails the whole INSERT. Other C0 control characters are accepted by
Postgres but are never meaningful in a narrative or a chart label; Gemini has
been seen writing them in place of accented letters ("Maranh\\x03o"), so they
are removed as well.

Tab, newline and carriage return are kept.

Stripping hides a model fault, so every call that actually removes something
logs a ``control_chars_stripped`` warning. Pass ``field`` to say which piece of
text it was; the log carries the removed code points and a short snippet around
the first one. A steady trickle of these warnings means the model is still
writing control characters and the earlier defences are not catching them.
"""

import re
from typing import Any

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

# C0 controls except \t (0x09), \n (0x0a), \r (0x0d), plus DEL.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


_CONTEXT_RADIUS = 20


def _strip(text: str) -> tuple[str, list[str], str]:
    """Return (clean text, removed characters, snippet around the first one)."""
    found = list(_CONTROL_CHARS.finditer(text))
    if not found:
        return text, [], ""
    first = found[0].start()
    snippet = text[max(0, first - _CONTEXT_RADIUS) : first + _CONTEXT_RADIUS]
    return (
        _CONTROL_CHARS.sub("", text),
        [m.group(0) for m in found],
        snippet,
    )


def _warn(field: str | None, removed: list[str], snippet: str) -> None:
    logger.warning(
        "control_chars_stripped",
        field=field,
        count=len(removed),
        codepoints=sorted({f"U+{ord(c):04X}" for c in removed}),
        context=snippet,
    )


def strip_control_chars(text: str, *, field: str | None = None) -> str:
    """Remove NUL and other control characters from ``text``.

    Logs a warning, tagged with ``field``, when anything was removed.
    """
    clean, removed, snippet = _strip(text)
    if removed:
        _warn(field, removed, snippet)
    return clean


def clean_json(value: Any, *, field: str | None = None) -> Any:
    """Return ``value`` with control characters stripped from every string.

    Walks dicts (keys too), lists and tuples; other types pass through. Meant
    for JSON-shaped data on its way into a JSONB column. Logs one warning for
    the whole structure, tagged with ``field``, when anything was removed.
    """
    hits: list[tuple[list[str], str]] = []
    clean = _clean_json(value, hits)
    if hits:
        removed = [c for chars, _ in hits for c in chars]
        _warn(field, removed, hits[0][1])
    return clean


def _clean_json(value: Any, hits: list[tuple[list[str], str]]) -> Any:
    if isinstance(value, str):
        clean, removed, snippet = _strip(value)
        if removed:
            hits.append((removed, snippet))
        return clean
    if isinstance(value, dict):
        return {
            _clean_json(k, hits): _clean_json(v, hits)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_clean_json(v, hits) for v in value]
    return value
