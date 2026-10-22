"""Query template variables: deterministic date tokens resolved at run time.

Case queries may contain ``{variable_name}`` tokens that are resolved to
absolute date strings when a run executes.  The YAML stores the template
form (and the uid hashes it), so the case identity is stable across months
while the prompt sent to the agent stays natural and current.

Supported variables are listed in ``TEMPLATE_VARS``. Unknown tokens are
caught by ``validate_templates``, which ``tools/check.py`` and
``tools/audit_cases.py`` call.
"""

from __future__ import annotations

import re
from datetime import datetime

_TOKEN_RE = re.compile(r"\{([a-z_]+)\}")

TEMPLATE_VARS: dict[str, str] = {
    "current_month": "current calendar month and year, e.g. 'August 2026'",
    "last_month": "previous calendar month and year, e.g. 'July 2026'",
    "current_year": "current four-digit year, e.g. '2026'",
}


def _resolve(name: str, now: datetime) -> str:
    if name == "current_month":
        return now.strftime("%B %Y")
    if name == "last_month":
        year, month = now.year, now.month - 1
        if month < 1:
            year -= 1
            month = 12
        return datetime(year, month, 1).strftime("%B %Y")
    if name == "current_year":
        return str(now.year)
    raise KeyError(name)


def resolve_templates(text: str, now: datetime | None = None) -> str:
    """Replace all ``{var}`` tokens in *text* with their current values.

    Raises ``KeyError`` on an unrecognised token (callers should validate
    at authoring time via ``validate_templates``).
    """
    if "{" not in text:
        return text
    now = now or datetime.now()
    return _TOKEN_RE.sub(lambda m: _resolve(m.group(1), now), text)


def validate_templates(text: str) -> list[str]:
    """Return a list of problems; empty means every token is recognised."""
    problems: list[str] = []
    for match in _TOKEN_RE.finditer(text):
        name = match.group(1)
        if name not in TEMPLATE_VARS:
            problems.append(f"unknown template variable {{{name}}}")
    return problems


def has_templates(text: str) -> bool:
    """True when *text* contains at least one ``{var}`` token."""
    return bool(_TOKEN_RE.search(text))
