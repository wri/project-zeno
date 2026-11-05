"""Reversible masking of place names that go into an LLM prompt.

Gemini Flash intermittently replaces an accented character in its structured
output with a control character: "Piauí" comes back as "Piau\\x00" and
"Maranhão" as "Maranh\\x03o". A NUL then makes the Postgres insert fail, and
any other control character is stored and shown to users as garbage.

Place names are where this has been seen, because the model copies them from
the prompt. So every place name that contains a non-ASCII character is swapped
for an opaque stand-in (``PLACE_1``, ``PLACE_2``, ...) before the prompt is
built, and the stand-ins are swapped back to the real names in the response.
The stand-ins are deliberately not transliterations ("Pará" -> "Para"): a
transliteration can equal an ordinary word the model writes on its own, and
restoring it would then corrupt a correct sentence. ``PLACE_1`` never is one.

What gets masked:

* The names passed in ``place_names`` (the areas of interest), as whole names
  and as each comma-separated part ("Alto Rio Guamá, Pará" also masks "Pará").
* In *data* fields (``learn=True``: chart JSON, executor output) every other
  word with a non-ASCII character, since names of sub-areas live there.
* In *prose* fields (the user query, dataset notes) only names already known
  from the above, so ordinary non-English prose is left readable.

ASCII-only names ("Brazil") are never masked: there is nothing to protect and
the narrative reads better with the real name.

This only protects words that came *from the input*. Accented characters the
model writes on its own (a Portuguese or Russian narrative, say) are not
covered.

Example::

    masker = PlaceMasker.for_texts(["Piauí"], chart_json, query)
    chart_json = masker.mask(chart_json, learn=True)
    query = masker.mask(query)
    ...
    narrative = masker.unmask(model_output)
"""

import re
from collections.abc import Iterable

# A "word" is a run of letters, digits and underscores in any script.
_WORD = re.compile(r"\w+")
_STAND_IN_PREFIX = "PLACE_"
_STAND_IN_IN_TEXT = re.compile(rf"{_STAND_IN_PREFIX}\d+")


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
        self._token_by_name: dict[str, str] = {}
        self._name_by_token: dict[str, str] = {}
        self._next_number = 1
        self._unmask_pattern: re.Pattern[str] | None = None
        variants = _name_variants(place_names)
        self._names_pattern = (
            re.compile(
                r"(?<!\w)(?:"
                + "|".join(re.escape(v) for v in variants)
                + r")(?!\w)"
            )
            if variants
            else None
        )

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

    def mask(self, text: str, *, learn: bool = False) -> str:
        """Replace place names in ``text`` with their stand-ins.

        With ``learn=True`` every word that has a non-ASCII character is
        treated as a place name and gets a stand-in. Without it, only names
        already known (from ``place_names`` or an earlier ``learn=True`` call)
        are replaced.
        """
        if not text or text.isascii():
            return text
        if self._names_pattern is not None:
            text = self._names_pattern.sub(
                lambda m: self._token_for(m.group(0)), text
            )

        def replace(match: re.Match[str]) -> str:
            word = match.group(0)
            if word.isascii():
                return word
            if learn or word in self._token_by_name:
                return self._token_for(word)
            return word

        return _WORD.sub(replace, text)

    def unmask(self, text: str) -> str:
        """Swap the stand-ins in ``text`` back to the real names."""
        if not text or not self._name_by_token:
            return text
        if self._unmask_pattern is None:
            # Longest first, so "PLACE_10" is never read as "PLACE_1".
            tokens = sorted(self._name_by_token, key=len, reverse=True)
            self._unmask_pattern = re.compile(
                r"(?<!\w)(?:"
                + "|".join(re.escape(t) for t in tokens)
                + r")(?!\w)"
            )
        return self._unmask_pattern.sub(
            lambda m: self._name_by_token[m.group(0)], text
        )

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
