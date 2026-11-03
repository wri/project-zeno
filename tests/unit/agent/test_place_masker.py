"""Unit tests for masking place names with opaque stand-ins before LLM calls."""

import pytest

from src.agent.subagents.analyst.place_masker import PlaceMasker


def _roundtrip(masker: PlaceMasker, text: str, **kwargs) -> str:
    masked = masker.mask(text, **kwargs)
    assert masker.unmask(masked) == text
    return masked


# --- known place names ------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["Piauí", "Maranhão", "Paraná", "Alto Rio Guamá", "São Paulo"]
)
def test_known_name_becomes_a_stand_in_and_comes_back(name):
    masker = PlaceMasker([name])
    masked = _roundtrip(masker, f"Loss in {name} rose.")
    assert masked == "Loss in PLACE_1 rose."
    assert masker.mapping == {"PLACE_1": name}


def test_multi_word_name_is_one_stand_in():
    masker = PlaceMasker(["Alto Rio Guamá"])
    assert (
        _roundtrip(masker, "Alto Rio Guamá lost 5 ha") == "PLACE_1 lost 5 ha"
    )


def test_comma_separated_parts_of_a_name_are_masked_too():
    masker = PlaceMasker(["Alto Rio Guamá, Pará, Brazil"])
    masked = _roundtrip(masker, "Pará and Alto Rio Guamá, Pará, Brazil")
    # The whole name is one stand-in and the part "Pará" another.
    assert masked == "PLACE_1 and PLACE_2"
    assert masker.mapping == {
        "PLACE_1": "Pará",
        "PLACE_2": "Alto Rio Guamá, Pará, Brazil",
    }


def test_longer_name_wins_over_a_shorter_name_inside_it():
    masker = PlaceMasker(["Guamá", "Alto Rio Guamá"])
    assert _roundtrip(masker, "Alto Rio Guamá, Guamá") == "PLACE_1, PLACE_2"


def test_ascii_names_are_left_alone():
    masker = PlaceMasker(["Brazil", "Peru"])
    text = "Loss in Brazil and Peru."
    assert masker.mask(text) is text
    assert masker.mapping == {}


def test_names_match_whole_words_only():
    masker = PlaceMasker(["Pará"])
    assert masker.mask("Paraná and Pará.") == "Paraná and PLACE_1."


def test_same_name_gets_the_same_stand_in_every_time():
    masker = PlaceMasker(["Piauí"])
    assert masker.mask("Piauí e Piauí") == "PLACE_1 e PLACE_1"
    assert masker.mapping == {"PLACE_1": "Piauí"}


def test_names_with_the_same_transliteration_stay_distinct():
    # "Pará" and "Pára" would both be "Para" if they were transliterated.
    masker = PlaceMasker(["Pará", "Pára"])
    assert _roundtrip(masker, "Pará e Pára") == "PLACE_1 e PLACE_2"


# --- learning names from data -----------------------------------------------


def test_data_fields_mask_every_non_ascii_word():
    masker = PlaceMasker()
    masked = _roundtrip(
        masker,
        '[{"municipio": "Altamira"}, {"municipio": "São Félix do Xingu"}]',
        learn=True,
    )
    assert masked == (
        '[{"municipio": "Altamira"}, {"municipio": "PLACE_1 PLACE_2 do Xingu"}]'
    )


def test_prose_fields_only_mask_names_already_known():
    masker = PlaceMasker(["Piauí"])
    masker.mask('{"area": "Guamá"}', learn=True)  # learns "Guamá"
    query = "Qual foi a perda arbórea em Piauí e Guamá no último ano?"
    masked = masker.mask(query)
    # Known names go; ordinary non-English prose stays readable.
    assert (
        masked
        == "Qual foi a perda arbórea em PLACE_2 e PLACE_1 no último ano?"
    )


def test_prose_does_not_learn_new_words():
    masker = PlaceMasker()
    text = "Perda arbórea no último ano"
    assert masker.mask(text) == text
    assert masker.mapping == {}


# --- restoring ---------------------------------------------------------------


def test_unmask_never_touches_words_the_model_wrote_itself():
    # The collision that motivated stand-ins: "Pará" must not turn a genuine
    # Portuguese "Para" into "Pará".
    masker = PlaceMasker(["Pará"])
    masker.mask("Pará")
    narrative = "Para o período, PLACE_1 perdeu 5 ha. Para Para."
    assert masker.unmask(narrative) == (
        "Para o período, Pará perdeu 5 ha. Para Para."
    )


def test_unmask_distinguishes_place_1_from_place_10():
    masker = PlaceMasker([f"Nomé{i}" for i in range(1, 12)])
    for i in range(1, 12):
        masker.mask(f"Nomé{i}")
    assert masker.unmask("PLACE_1, PLACE_10, PLACE_11") == (
        "Nomé1, Nomé10, Nomé11"
    )


def test_unmask_handles_punctuation_and_possessives():
    masker = PlaceMasker(["Piauí"])
    masker.mask("Piauí")
    assert masker.unmask("PLACE_1's loss; (PLACE_1), PLACE_1.") == (
        "Piauí's loss; (Piauí), Piauí."
    )


def test_unmask_leaves_longer_words_alone():
    masker = PlaceMasker(["Piauí"])
    masker.mask("Piauí")
    assert masker.unmask("PLACE_1x xPLACE_1 PLACE_1_a") == (
        "PLACE_1x xPLACE_1 PLACE_1_a"
    )


def test_unmask_without_mapping_is_a_no_op():
    masker = PlaceMasker()
    assert masker.unmask("PLACE_1") == "PLACE_1"
    assert masker.unmask("") == ""


# --- safety ------------------------------------------------------------------


def test_stand_ins_skip_numbers_that_already_occur_in_the_input():
    text = "The text mentions PLACE_1 and Piauí."
    masker = PlaceMasker.for_texts(["Piauí"], text)
    assert masker.mask(text) == "The text mentions PLACE_1 and PLACE_2."
    # Only the stand-in it created is restored, never the genuine PLACE_1.
    assert masker.unmask("PLACE_1 and PLACE_2") == "PLACE_1 and Piauí"


def test_ascii_text_is_returned_untouched():
    masker = PlaceMasker(["Piauí"])
    text = "Tree cover loss in Brazil, 2020."
    assert masker.mask(text, learn=True) is text


def test_punctuation_and_typographic_symbols_are_left_alone():
    masker = PlaceMasker()
    masked = _roundtrip(
        masker, "Piauí — Maranhão → “quoted” 3,600 ha", learn=True
    )
    assert masked == "PLACE_1 — PLACE_2 → “quoted” 3,600 ha"


@pytest.mark.parametrize(
    "name", ["Москва", "中国", "القاهرة", "Hà Nội", "İstanbul"]
)
def test_other_scripts_roundtrip(name):
    masker = PlaceMasker([name])
    assert _roundtrip(masker, f"Loss in {name}.") == "Loss in PLACE_1."

    # Learned from data, each non-ASCII word is masked separately.
    learner = PlaceMasker()
    masked = _roundtrip(learner, f"Loss in {name}.", learn=True)
    assert masked.isascii()
