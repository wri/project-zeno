import unicodedata

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

_KEEP = {"\t", "\n", "\r"}
_ALSO_STRIP = {"\ufffd"}
_SNIPPET_RADIUS = 20


def _is_stripped(c: str) -> bool:
    return c in _ALSO_STRIP or (
        c not in _KEEP and unicodedata.category(c) == "Cc"
    )


def _escape(c: str) -> str:
    return c.encode("unicode_escape").decode("ascii") if _is_stripped(c) else c


def _snippet(text: str) -> str:
    first = next(i for i, c in enumerate(text) if _is_stripped(c))
    start = max(0, first - _SNIPPET_RADIUS)
    window = text[start : first + _SNIPPET_RADIUS + 1]
    return "".join(_escape(c) for c in window)


def strip_control_chars(text: str, *, field: str) -> str:
    removed = [c for c in text if _is_stripped(c)]
    if not removed:
        return text
    cleaned = "".join(c for c in text if not _is_stripped(c))
    logger.warning(
        "control_chars_stripped",
        field=field,
        count=len(removed),
        codepoints=[f"U+{ord(c):04X}" for c in dict.fromkeys(removed)],
        snippet=_snippet(text),
    )
    return cleaned
