"""Judge backend selection and model naming.

Default behaviour remains Anthropic Haiku. An alternative backend can route
judge calls through OpenRouter Decisions with TypeSafe JEV.
"""

from __future__ import annotations

import os

JUDGE_BACKEND_ENV_VAR = "GOLD_JUDGE_BACKEND"

JUDGE_BACKEND_HAIKU = "haiku"
JUDGE_BACKEND_OPENROUTER_JEV = "openrouter-jev-decisions"
DEFAULT_JUDGE_BACKEND = JUDGE_BACKEND_HAIKU

JUDGE_BACKEND_CHOICES = (
    JUDGE_BACKEND_HAIKU,
    JUDGE_BACKEND_OPENROUTER_JEV,
)

HAIKU_MODEL = "claude-haiku-4-5"
OPENROUTER_JEV_MODEL = "typesafe/jev-1.13"

JUDGE_MODEL_BY_BACKEND = {
    JUDGE_BACKEND_HAIKU: HAIKU_MODEL,
    JUDGE_BACKEND_OPENROUTER_JEV: OPENROUTER_JEV_MODEL,
}


def resolve_judge_backend(explicit: str | None = None) -> str:
    """Resolve the active judge backend from explicit value or environment."""
    value = (
        explicit or os.environ.get(JUDGE_BACKEND_ENV_VAR) or DEFAULT_JUDGE_BACKEND
    ).strip()
    if value not in JUDGE_MODEL_BY_BACKEND:
        allowed = ", ".join(sorted(JUDGE_MODEL_BY_BACKEND))
        raise ValueError(f"unknown judge backend {value!r}; expected one of: {allowed}")
    return value


def judge_model_for_backend(backend: str) -> str:
    """Canonical model label recorded on run records."""
    resolved = resolve_judge_backend(backend)
    return JUDGE_MODEL_BY_BACKEND[resolved]
