"""Reversible ASCII sanitizing of words that go into an LLM prompt.

Gemini Flash intermittently replaces an accented character in its structured
output with a control character: "Piauí" comes back as "Piau\\x00" and
"Maranhão" as "Maranh\\x03o". A NUL then makes the Postgres insert fail, and
any other control character is stored and shown to users as garbage.

To keep the model from ever having to copy such a word, every word that
contains a non-ASCII character is swapped for an ASCII stand-in before the
prompt is built (``Piauí`` -> ``Piaui``), and the stand-ins are swapped back to
the original words in the model's response.

This only protects words that came *from the input*. Accented characters the
model writes on its own (a Portuguese or Russian narrative, say) are not
covered.

Example::

    sanitizer = AsciiSanitizer.for_texts(query, context)
    prompt_query = sanitizer.sanitize(query)
    ...
    narrative = sanitizer.restore(model_output)
"""

import re

from unidecode import unidecode

# A "word" is a run of letters, digits and underscores in any script.
_WORD = re.compile(r"\w+")
_SAFE_TOKEN = re.compile(r"[A-Za-z0-9_]+")
_FALLBACK_STEM = "TERM"


def _has_non_ascii(word: str) -> bool:
    return not word.isascii()


class AsciiSanitizer:
    """Replaces non-ASCII words with ASCII stand-ins and restores them.

    One instance is meant for one model call: it remembers which stand-in
    stands for which original word, so ``restore`` can undo ``sanitize``.
    """

    def __init__(self, reserved: frozenset[str] = frozenset()):
        # ASCII words that already occur in the input. A stand-in must never
        # equal one of them, or `restore` would rewrite a genuine word.
        self._reserved = set(reserved)
        self._token_by_original: dict[str, str] = {}
        self._original_by_token: dict[str, str] = {}
        self._restore_pattern: re.Pattern[str] | None = None

    @classmethod
    def for_texts(cls, *texts: str) -> "AsciiSanitizer":
        """Build a sanitizer that avoids every ASCII word in ``texts``."""
        reserved = {
            word
            for text in texts
            for word in _WORD.findall(text or "")
            if word.isascii()
        }
        return cls(frozenset(reserved))

    @property
    def mapping(self) -> dict[str, str]:
        """Stand-in -> original word, for logging and tests."""
        return dict(self._original_by_token)

    def sanitize(self, text: str) -> str:
        """Replace every word that has a non-ASCII character."""
        if not text or text.isascii():
            return text
        return _WORD.sub(self._replace, text)

    def restore(self, text: str) -> str:
        """Swap the stand-ins in ``text`` back to the original words."""
        if not text or not self._original_by_token:
            return text
        if self._restore_pattern is None:
            # Longest first, so "Para_1" is never read as "Para".
            tokens = sorted(self._original_by_token, key=len, reverse=True)
            self._restore_pattern = re.compile(
                r"(?<!\w)(?:"
                + "|".join(re.escape(t) for t in tokens)
                + r")(?!\w)"
            )
        return self._restore_pattern.sub(
            lambda m: self._original_by_token[m.group(0)], text
        )

    def _replace(self, match: re.Match[str]) -> str:
        word = match.group(0)
        if not _has_non_ascii(word):
            return word
        return self._token_for(word)

    def _token_for(self, word: str) -> str:
        token = self._token_by_original.get(word)
        if token is not None:
            return token

        # unidecode spaces out multi-syllable transliterations ("Zhong Guo "),
        # which would not survive as one word, so join them with "_".
        stem = re.sub(r"\s+", "_", unidecode(word).strip())
        if not _SAFE_TOKEN.fullmatch(stem):
            # Nothing usable (emoji, symbols, empty transliteration).
            stem = _FALLBACK_STEM
        token = stem
        counter = 1
        while token in self._reserved or token in self._original_by_token:
            # Taken by a real input word or by a different original word
            # ("Pará" and "Para"), so make the stand-in unique.
            counter += 1
            token = f"{stem}_{counter}"
        self._token_by_original[word] = token
        self._original_by_token[token] = word
        self._restore_pattern = None
        return token
