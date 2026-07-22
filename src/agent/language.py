"""Per-turn conversation language resolution.

Precedence: explicit user profile preference > langid-detected language of
the latest human message > whatever language was already active earlier in
the thread. The third case needs no code here — ``AgentState.language`` is a
last-write-wins field (see src/agent/state.py), so callers simply skip
writing it when `resolve_language` returns None and the thread's prior value
carries over untouched.
"""

from typing import Optional

import langid

from src.api.user_profile_configs.languages import LANGUAGES

DEFAULT_LANGUAGE = "en"

# Below this many characters langid's confidence is too noisy to trust
# (mirrors the threshold used for trace analytics detection, see
# src/api/services/langfuse/parse.py:_detect_language).
_MIN_DETECTION_CHARS = 12


def detect_language(text: Optional[str]) -> Optional[str]:
    """Best-effort ISO 639-1 code for `text`, or None if undetectable."""
    if not text or len(text.strip()) < _MIN_DETECTION_CHARS:
        return None
    code, _score = langid.classify(text)
    return code


def resolve_language(
    *,
    preferred_language_code: Optional[str] = None,
    query: Optional[str] = None,
) -> Optional[str]:
    """Resolve the language to write into AgentState for this turn.

    Returns None when there's nothing new to say, meaning the caller should
    leave state["language"] unset so the thread's last-known value (or the
    "en" display default) carries over.
    """
    if preferred_language_code:
        return preferred_language_code
    return detect_language(query)


def language_name(code: Optional[str]) -> str:
    """Human-readable name for a language code, for prompts/session display."""
    if not code:
        return LANGUAGES[DEFAULT_LANGUAGE]
    return LANGUAGES.get(code, code)
