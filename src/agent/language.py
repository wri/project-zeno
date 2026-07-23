"""Per-conversation language resolution.

Precedence: explicit user profile preference > LLM-detected language of the
first human message in the thread > whatever language was already active
earlier in the thread. The third case needs no code here —
``AgentState.language`` is a last-write-wins field (see src/agent/state.py),
so callers simply skip writing it when `resolve_language` returns None and
the thread's prior value carries over untouched.

Detection runs once per conversation, not every turn: once a thread has a
resolved language, callers pass `already_resolved=True` and detection is
skipped, both to save the latency of the LLM call and because re-detecting
on every message risks flip-flopping the thread's language on short or
code-mixed follow-ups.

We used to detect with `langid` (a statistical n-gram classifier), but it
misclassifies short or place-name-heavy text with real confidence — e.g. the
German "in puri indien, gibt es elefanten?" was classified as Catalan. An LLM
call is slower (~0.5s with a minimal-thinking Gemini Flash-Lite call) but
actually understands the sentence instead of scoring character frequencies.
"""

from typing import Optional

from src.agent.llms import GEMINI_FLASH_LITE_MINIMAL
from src.api.user_profile_configs.languages import LANGUAGES
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

DEFAULT_LANGUAGE = "en"

# The languages i18n has pre-built templates for (src/agent/i18n.py::MESSAGES).
# Detection is constrained to this set: an LLM asked for "the ISO code" on an
# ambiguous or joke input will happily invent something plausible-looking, and
# an unsupported code silently becomes a literal "write in {code}" instruction
# to downstream prompts (see language_name below) instead of erroring.
SUPPORTED_LANGUAGES = [
    "en", "es", "fr", "pt", "id", "de", "it", "nl",
    "ru", "zh", "ar", "hi", "vi", "sw", "tr",
]  # fmt: skip

# Below this many characters there isn't enough signal to bother with a
# detection call at all (e.g. "hi", "ok").
_MIN_DETECTION_CHARS = 12

_UNSURE = "UNSURE"

_DETECTION_PROMPT = (
    "Identify the language of the user message below.\n"
    "Reply with ONLY one of these ISO 639-1 codes: "
    f"{', '.join(SUPPORTED_LANGUAGES)}, or {_UNSURE} if you cannot "
    "confidently tell.\n"
    "No other text.\n\n"
    'Message: "{text}"'
)


def _extract_text(content) -> str:
    """Normalize a LangChain message `.content` (str, or a list of text /
    content-block parts, depending on provider) into plain text."""
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            parts.append(block.get("text", ""))
    return "".join(parts)


async def detect_language(text: Optional[str]) -> Optional[str]:
    """Best-effort ISO 639-1 code for `text`, or None if undetectable."""
    if not text or len(text.strip()) < _MIN_DETECTION_CHARS:
        return None

    prompt = _DETECTION_PROMPT.format(text=text.strip())
    try:
        response = await GEMINI_FLASH_LITE_MINIMAL.ainvoke(prompt)
    except Exception:
        logger.exception("language_detection_failed")
        return None

    code = _extract_text(response.content).strip().lower()
    return code if code in SUPPORTED_LANGUAGES else None


async def resolve_language(
    *,
    preferred_language_code: Optional[str] = None,
    query: Optional[str] = None,
    already_resolved: bool = False,
) -> Optional[str]:
    """Resolve the language to write into AgentState for this turn.

    Returns None when there's nothing new to say, meaning the caller should
    leave state["language"] unset so the thread's last-known value (or the
    "en" display default) carries over. `already_resolved` should reflect
    whether the thread already has a language in its persisted state — when
    True, detection is skipped so it only ever runs once per conversation.
    """
    if preferred_language_code:
        return preferred_language_code
    if already_resolved:
        return None
    return await detect_language(query)


def language_name(code: Optional[str]) -> str:
    """Human-readable name for a language code, for prompts/session display."""
    if not code:
        return LANGUAGES[DEFAULT_LANGUAGE]
    return LANGUAGES.get(code, code)
