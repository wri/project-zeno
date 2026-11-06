"""Reversible masking of place names that go into an LLM prompt.

Gemini Flash intermittently replaces an accented character in its structured
output with a control character: "Piauí" comes back as "Piau\\x00" and
"Maranhão" as "Maranh\\x03o". A NUL then makes the Postgres insert fail, and
any other control character is stored and shown to users as garbage.

Place names are where this has been seen, because the model copies them from
the prompt. So every listed place name that contains a non-ASCII character is
swapped for an opaque stand-in (``PLACE_1``, ``PLACE_2``, ...) before the
prompt is built, and the stand-ins are swapped back to the real names in the
response. The stand-ins are deliberately not transliterations ("Pará" ->
"Para"): a transliteration can equal an ordinary word the model writes on its
own, and restoring it would then corrupt a correct sentence. ``PLACE_1`` never
is one.

Only the names passed in ``place_names`` (the areas of interest) are masked,
as whole names and as each comma-separated part ("Alto Rio Guamá, Pará" also
masks "Pará"). Every other word is left exactly as it is, in every script:
chart titles, axis labels, category values and the user's own sentences are
often written in the user's language, and masking them would leave the model
nothing readable to work from. ASCII-only names ("Brazil") are never masked:
there is nothing to protect and the narrative reads better with the real name.

Known limits:

* A name is matched exactly. An inflected form ("Московской области" for the
  listed "Московская область") is not recognised and passes through.
* A name in a script without spaces also matches inside a longer word: with
  "京" listed, "东京" becomes "东PLACE_1". The real name is still restored.
* Sub-area names that appear only in the data (municipalities in a chart's
  rows, say) are not masked.
* Accented characters the model writes on its own (a Portuguese or Russian
  narrative, say) are not covered.

The strip-and-log backstop in ``text_sanitize`` catches what slips through.

Scripts written without spaces (Chinese, Japanese, Thai, ...) are handled: a
name there is found inside a sentence, and a stand-in that would touch a digit
or letter ("云南省2023年") gets a space so it stays a separate token.

Example::

    masker = PlaceMasker.for_texts(["Piauí"], query, chart_json)
    prompt_query = masker.mask(query)
    ...
    narrative = masker.unmask(model_output)
"""

import re
import unicodedata
from collections.abc import Iterable

_STAND_IN_PREFIX = "PLACE_"
_STAND_IN_IN_TEXT = re.compile(rf"{_STAND_IN_PREFIX}\d+")
_ASCII_WORD_CHAR = re.compile(r"[A-Za-z0-9_]")
# Stand-ins are ASCII, so only an adjacent ASCII letter, digit or underscore
# can make one part of a longer token ("PLACE_12", "xPLACE_1").
_UNMASK_BOUNDARY = (r"(?<![A-Za-z0-9_])", r"(?![A-Za-z0-9_])")

# Scripts whose words are not separated by spaces: Thai, Lao, Myanmar, Khmer,
# Hiragana and Katakana, CJK ideographs (incl. extensions and compatibility).
_SPACELESS_SCRIPTS = re.compile(
    "[฀-໿က-႟ក-៿぀-ヿ㐀-䶿一-鿿豈-﫿\U00020000-\U0002ffff]"
)


def _is_spaceless(char: str) -> bool:
    return bool(_SPACELESS_SCRIPTS.match(char))


def _is_word_char(char: str) -> bool:
    """Whether ``char`` continues a word, for matching a name as a whole word.

    Letters, digits, underscore and combining marks (Hindi vowel signs, Latin
    diacritics) do. Characters of scripts without spaces never do, because a
    name written in them is followed directly by the next word.
    """
    if _is_spaceless(char):
        return False
    return (
        char.isalnum() or char == "_" or unicodedata.category(char)[0] == "M"
    )


def _name_variants(place_names: Iterable[str]) -> list[str]:
    """Non-ASCII names and their comma-separated parts, longest first."""
    variants: set[str] = set()
    for name in place_names:
        if not name:
            continue
        for candidate in (name, *name.split(",")):
            candidate = candidate.strip()
            if candidate and not candidate.isascii():
                variants.add(candidate)
    # Longest first, so "Alto Rio Guamá" wins over "Guamá".
    return sorted(variants, key=len, reverse=True)


def _is_whole_word(text: str, start: int, end: int, name: str) -> bool:
    """Whether ``text[start:end]`` is ``name`` standing as a word of its own."""
    before_ok = (
        start == 0
        or _is_spaceless(name[0])
        or not _is_word_char(text[start - 1])
    )
    after_ok = (
        end == len(text)
        or _is_spaceless(name[-1])
        or not _is_word_char(text[end])
    )
    return before_ok and after_ok


class PlaceMasker:
    """Replaces non-ASCII place names with ``PLACE_n`` stand-ins and back.

    One instance is meant for one model call: it remembers which stand-in
    stands for which name, so ``unmask`` can undo ``mask``.
    """

    def __init__(
        self,
        place_names: Iterable[str] = (),
        reserved: Iterable[str] = (),
    ):
        # Stand-ins that already occur in the input. Reusing one would make
        # `unmask` rewrite text that was never a place name.
        self._reserved = set(reserved)
        self._variants = _name_variants(place_names)
        self._token_by_name: dict[str, str] = {}
        self._name_by_token: dict[str, str] = {}
        self._next_number = 1
        self._unmask_pattern: re.Pattern[str] | None = None

    @classmethod
    def for_texts(
        cls, place_names: Iterable[str], *texts: str
    ) -> "PlaceMasker":
        """Build a masker that avoids stand-ins already present in ``texts``."""
        reserved = {
            token
            for text in texts
            for token in _STAND_IN_IN_TEXT.findall(text or "")
        }
        return cls(place_names, reserved)

    @property
    def mapping(self) -> dict[str, str]:
        """Stand-in -> real name, for logging and tests."""
        return dict(self._name_by_token)

    def mask(self, text: str) -> str:
        """Replace the listed place names in ``text`` with their stand-ins."""
        if not text or text.isascii() or not self._variants:
            return text
        spans = self._find_names(text)
        if not spans:
            return text

        result = ""
        position = 0
        for start, end in spans:
            result += text[position:start]
            if result and _ASCII_WORD_CHAR.match(result[-1]):
                result += " "  # keep "2023" and "PLACE_1" apart
            result += self._token_for(text[start:end])
            if end < len(text) and _ASCII_WORD_CHAR.match(text[end]):
                result += " "
            position = end
        return result + text[position:]

    def unmask(self, text: str) -> str:
        """Swap the stand-ins in ``text`` back to the real names."""
        if not text or not self._name_by_token:
            return text
        if self._unmask_pattern is None:
            # Longest first, so "PLACE_10" is never read as "PLACE_1".
            tokens = sorted(self._name_by_token, key=len, reverse=True)
            before, after = _UNMASK_BOUNDARY
            self._unmask_pattern = re.compile(
                before
                + "(?:"
                + "|".join(re.escape(t) for t in tokens)
                + ")"
                + after
            )
        return self._unmask_pattern.sub(
            lambda m: self._name_by_token[m.group(0)], text
        )

    def _find_names(self, text: str) -> list[tuple[int, int]]:
        """Non-overlapping spans of listed names, earliest and longest first."""
        found: list[tuple[int, int]] = []
        for name in self._variants:
            index = text.find(name)
            while index != -1:
                end = index + len(name)
                if _is_whole_word(text, index, end, name):
                    found.append((index, end))
                index = text.find(name, index + 1)
        found.sort(key=lambda span: (span[0], span[0] - span[1]))
        chosen: list[tuple[int, int]] = []
        covered_to = 0
        for start, end in found:
            if start >= covered_to:
                chosen.append((start, end))
                covered_to = end
        return chosen

    def _token_for(self, name: str) -> str:
        token = self._token_by_name.get(name)
        if token is not None:
            return token
        token = f"{_STAND_IN_PREFIX}{self._next_number}"
        while token in self._reserved:
            self._next_number += 1
            token = f"{_STAND_IN_PREFIX}{self._next_number}"
        self._next_number += 1
        self._token_by_name[name] = token
        self._name_by_token[token] = name
        self._unmask_pattern = None
        return token
