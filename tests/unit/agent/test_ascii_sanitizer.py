"""Unit tests for the reversible ASCII sanitizer used before LLM calls."""

import pytest

from src.agent.subagents.analyst.ascii_sanitizer import AsciiSanitizer


def _roundtrip(*texts: str) -> list[tuple[str, str]]:
    sanitizer = AsciiSanitizer.for_texts(*texts)
    clean = [sanitizer.sanitize(t) for t in texts]
    assert all(c.isascii() or "—" in c for c in clean)
    assert [sanitizer.restore(c) for c in clean] == list(texts)
    return list(zip(texts, clean))


@pytest.mark.parametrize(
    "original, expected",
    [
        ("Piauí", "Piaui"),
        ("Maranhão", "Maranhao"),
        ("Paraná", "Parana"),
        ("Alto Rio Guamá", "Alto Rio Guama"),
        ("São Paulo", "Sao Paulo"),
    ],
)
def test_accented_words_become_ascii_and_come_back(original, expected):
    sanitizer = AsciiSanitizer.for_texts(original)
    assert sanitizer.sanitize(original) == expected
    assert sanitizer.restore(expected) == original


def test_ascii_text_is_returned_untouched():
    sanitizer = AsciiSanitizer.for_texts("Tree cover loss in Brazil, 2020.")
    text = "Tree cover loss in Brazil, 2020."
    assert sanitizer.sanitize(text) is text
    assert sanitizer.restore(text) is text
    assert sanitizer.mapping == {}


def test_only_words_with_non_ascii_characters_change():
    sanitizer = AsciiSanitizer.for_texts("Loss in Piauí (Brazil): 12%")
    assert (
        sanitizer.sanitize("Loss in Piauí (Brazil): 12%")
        == "Loss in Piaui (Brazil): 12%"
    )


def test_punctuation_and_typographic_symbols_are_left_alone():
    text = "Piauí — Maranhão → 3,600 ha; “quoted” Ceará."
    sanitizer = AsciiSanitizer.for_texts(text)
    clean = sanitizer.sanitize(text)
    assert clean == "Piaui — Maranhao → 3,600 ha; “quoted” Ceara."
    assert sanitizer.restore(clean) == text


def test_repeated_word_uses_one_stand_in():
    sanitizer = AsciiSanitizer.for_texts("Piauí e Piauí")
    assert sanitizer.sanitize("Piauí e Piauí") == "Piaui e Piaui"
    assert sanitizer.mapping == {"Piaui": "Piauí"}


def test_same_sanitizer_is_shared_across_fields():
    pairs = _roundtrip("Loss in Piauí", '{"title": "Piauí loss"}')
    assert pairs[0][1] == "Loss in Piaui"
    assert pairs[1][1] == '{"title": "Piaui loss"}'


def test_restores_every_occurrence_in_a_narrative():
    sanitizer = AsciiSanitizer.for_texts("Piauí")
    sanitizer.sanitize("Piauí")
    narrative = "Piaui lost 3,600 ha. In Piaui, loss peaked in 2022."
    assert sanitizer.restore(narrative) == (
        "Piauí lost 3,600 ha. In Piauí, loss peaked in 2022."
    )


def test_does_not_restore_inside_longer_words():
    sanitizer = AsciiSanitizer.for_texts("Piauí")
    sanitizer.sanitize("Piauí")
    assert sanitizer.restore("Piauiense Piaui_x xPiaui") == (
        "Piauiense Piaui_x xPiaui"
    )


def test_two_originals_with_the_same_ascii_form_stay_distinct():
    # "Pará" (a state) and "Pára" would both transliterate to "Para".
    text = "Pará e Pára"
    sanitizer = AsciiSanitizer.for_texts(text)
    clean = sanitizer.sanitize(text)
    assert clean == "Para e Para_2"
    assert sanitizer.restore(clean) == text


def test_stand_in_never_equals_a_word_already_in_the_input():
    # "Para" is a real input word, so the stand-in for "Pará" must differ,
    # otherwise restore would rewrite the genuine "Para".
    text = "Para Pará"
    sanitizer = AsciiSanitizer.for_texts(text)
    clean = sanitizer.sanitize(text)
    assert clean == "Para Para_2"
    assert sanitizer.restore(clean) == text


def test_emoji_is_not_a_word_and_is_left_alone():
    sanitizer = AsciiSanitizer.for_texts("😀 ok")
    assert sanitizer.sanitize("😀 ok") == "😀 ok"


def test_word_with_no_ascii_form_gets_a_fallback_stand_in(monkeypatch):
    monkeypatch.setattr(
        "src.agent.subagents.analyst.ascii_sanitizer.unidecode", lambda w: ""
    )
    sanitizer = AsciiSanitizer.for_texts("ü ö")
    clean = sanitizer.sanitize("ü ö")
    assert clean == "TERM TERM_2"
    assert sanitizer.restore(clean) == "ü ö"


@pytest.mark.parametrize(
    "original", ["Москва", "中国", "القاهرة", "Ho Chí Minh", "İstanbul"]
)
def test_other_scripts_roundtrip(original):
    _roundtrip(original)


def test_multi_syllable_transliteration_stays_one_word():
    # unidecode renders "中国" as "Zhong Guo "; the stand-in must be one word.
    sanitizer = AsciiSanitizer.for_texts("中国")
    assert sanitizer.sanitize("中国") == "Zhong_Guo"


def test_restore_without_mapping_is_a_no_op():
    sanitizer = AsciiSanitizer()
    assert sanitizer.restore("Piaui") == "Piaui"
    assert sanitizer.restore("") == ""
