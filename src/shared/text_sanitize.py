import unicodedata

_KEEP = {"\t", "\n", "\r"}
_ALSO_STRIP = {"\ufffd"}


def strip_control_chars(text: str) -> str:
    return "".join(
        c
        for c in text
        if c not in _ALSO_STRIP
        and (c in _KEEP or unicodedata.category(c) != "Cc")
    )
