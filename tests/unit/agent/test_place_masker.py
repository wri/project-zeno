"""Unit tests for masking place names with opaque stand-ins before LLM calls."""

import pytest

from src.agent.subagents.analyst.place_masker import PlaceMasker


def _roundtrip(masker: PlaceMasker, text: str) -> str:
    masked = masker.mask(text)
    assert masker.unmask(masked) == text
    return masked


# --- listed place names -------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["Piauí", "Maranhão", "Paraná", "Alto Rio Guamá", "São Paulo"]
)
def test_listed_name_becomes_a_stand_in_and_comes_back(name):
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
    assert masker.mask(text) == text
    assert masker.mapping == {}


def test_names_match_whole_words_only():
    masker = PlaceMasker(["Pará"])
    assert masker.mask("Paraná and Pará.") == "Paraná and PLACE_1."
    assert masker.mask("Pará2 and Pará_x") == "Pará2 and Pará_x"


def test_same_name_gets_the_same_stand_in_every_time():
    masker = PlaceMasker(["Piauí"])
    assert masker.mask("Piauí e Piauí") == "PLACE_1 e PLACE_1"
    assert masker.mapping == {"PLACE_1": "Piauí"}


def test_names_with_the_same_transliteration_stay_distinct():
    # "Pará" and "Pára" would both be "Para" if they were transliterated.
    masker = PlaceMasker(["Pará", "Pára"])
    assert _roundtrip(masker, "Pará e Pára") == "PLACE_1 e PLACE_2"


def test_without_listed_names_nothing_changes():
    masker = PlaceMasker()
    text = "Perda arbórea em Piauí"
    assert masker.mask(text) == text
    assert masker.mapping == {}


# --- words that are not listed names stay exactly as written ----------------


def test_unlisted_non_ascii_words_are_never_masked():
    masker = PlaceMasker(["Piauí"])
    text = "Perda arbórea em Piauí e Guamá no último ano"
    assert (
        masker.mask(text) == "Perda arbórea em PLACE_1 e Guamá no último ano"
    )


def test_localised_chart_text_is_left_readable():
    masker = PlaceMasker(["Московская область"])
    chart = (
        '{"title": "Потеря лесного покрова", "x_axis": "Год", '
        '"y_axis": "Площадь (га)", "series_fields": ["Естественный лес"]}'
    )
    assert masker.mask(chart) == chart
    assert masker.mapping == {}


def test_inflected_forms_are_not_recognised():
    # Documented limit: only the exact listed form is masked.
    masker = PlaceMasker(["Московская область"])
    text = "Потеря леса в Московской области"
    assert masker.mask(text) == text


# --- the collisions the stand-ins exist to prevent ----------------------------


def test_portuguese_example_para_and_e_are_never_rewritten():
    query = "Qual é o desmatamento no Pará?"
    context = "Total loss in Pará: 3,600 ha"
    masker = PlaceMasker.for_texts(["Pará"], query, context)

    # The accented "é" is not a place name and is left as it is.
    assert masker.mask(query) == "Qual é o desmatamento no PLACE_1?"
    assert masker.mask(context) == "Total loss in PLACE_1: 3,600 ha"
    assert masker.unmask(
        "O PLACE_1 perdeu 3.600 ha entre 2021 e 2023. Para comparar, a perda caiu."
    ) == (
        "O Pará perdeu 3.600 ha entre 2021 e 2023. Para comparar, a perda caiu."
    )


def test_spanish_example_esta_and_pérdida_are_never_rewritten():
    query = "¿Cómo está la pérdida de bosque en Perú?"
    masker = PlaceMasker.for_texts(["Perú"], query)

    assert masker.mask(query) == (
        "¿Cómo está la pérdida de bosque en PLACE_1?"
    )
    assert masker.unmask(
        "esta región muestra una pérdida; PLACE_1 perdió 9 ha. "
        "Como resultado, está claro."
    ) == (
        "esta región muestra una pérdida; Perú perdió 9 ha. "
        "Como resultado, está claro."
    )


def test_unmask_never_touches_words_the_model_wrote_itself():
    masker = PlaceMasker(["Pará"])
    masker.mask("Pará")
    narrative = "Para o período, PLACE_1 perdeu 5 ha. Para Para."
    assert masker.unmask(narrative) == (
        "Para o período, Pará perdeu 5 ha. Para Para."
    )


# --- non-Latin scripts ---------------------------------------------------------


@pytest.mark.parametrize(
    "name, query, masked",
    [
        pytest.param(
            "Московская область",
            "Сколько леса потеряла Московская область в 2023 году?",
            "Сколько леса потеряла PLACE_1 в 2023 году?",
            id="russian",
        ),
        pytest.param(
            "云南省",
            "中国云南省2023年的森林损失是多少？",
            "中国PLACE_1 2023年的森林损失是多少？",
            id="chinese-name-touching-digits",
        ),
        pytest.param(
            "الجزائر",
            "كم فقدت الجزائر من الغطاء الشجري في عام 2023؟",
            "كم فقدت PLACE_1 من الغطاء الشجري في عام 2023؟",
            id="arabic",
        ),
        pytest.param(
            "उत्तराखंड",
            "2023 में उत्तराखंड ने कितना वन खोया?",
            "2023 में PLACE_1 ने कितना वन खोया?",
            id="hindi",
        ),
    ],
)
def test_only_the_area_name_changes_in_a_non_latin_query(name, query, masked):
    masker = PlaceMasker.for_texts([name], query)
    assert masker.mask(query) == masked
    assert masker.mapping == {"PLACE_1": name}


def test_chinese_name_is_found_inside_a_sentence():
    masker = PlaceMasker(["云南省"])
    assert masker.mask("中国云南省的森林") == "中国PLACE_1的森林"


def test_chinese_stand_in_touching_a_digit_or_letter_gets_a_space():
    masker = PlaceMasker(["云南省"])
    # Without the space this would read as the different token PLACE_12023.
    assert masker.mask("云南省2023年") == "PLACE_1 2023年"
    assert masker.mask("2023云南省") == "2023 PLACE_1"
    assert masker.mask("云南省abc") == "PLACE_1 abc"


def test_adjacent_chinese_names_stay_separate_tokens():
    masker = PlaceMasker(["云南省", "昆明市"])
    assert masker.mask("云南省昆明市2023") == "PLACE_1 PLACE_2 2023"


def test_latin_name_next_to_chinese_text_is_found():
    masker = PlaceMasker(["Piauí"])
    assert masker.mask("巴西Piauí州") == "巴西PLACE_1州"


@pytest.mark.parametrize(
    "name, model_output, restored",
    [
        pytest.param(
            "云南省",
            "PLACE_1的森林损失在2023年为12公顷",
            "云南省的森林损失在2023年为12公顷",
            id="chinese-directly-followed-by-text",
        ),
        pytest.param(
            "Московская область",
            "PLACE_1 потеряла 12 га леса",
            "Московская область потеряла 12 га леса",
            id="russian",
        ),
        pytest.param(
            "उत्तराखंड",
            "PLACE_1 ने 12 हेक्टेयर वन खोया",
            "उत्तराखंड ने 12 हेक्टेयर वन खोया",
            id="hindi",
        ),
        pytest.param(
            "الجزائر",
            "فقدت PLACE_1 12 هكتارا",
            "فقدت الجزائر 12 هكتارا",
            id="arabic",
        ),
    ],
)
def test_unmask_restores_names_inside_non_latin_text(
    name, model_output, restored
):
    masker = PlaceMasker([name])
    masker.mask(name)
    assert masker.unmask(model_output) == restored


def test_combining_marks_count_as_part_of_a_word():
    # "ी" (a Hindi vowel sign) continues the word, so this is not the listed
    # name.
    masker = PlaceMasker(["उत्तराखंड"])
    text = "उत्तराखंडी लोग"
    assert masker.mask(text) == text


@pytest.mark.parametrize(
    "name", ["Москва", "中国", "القاهرة", "Hà Nội", "İstanbul"]
)
def test_other_scripts_roundtrip(name):
    masker = PlaceMasker([name])
    assert _roundtrip(masker, f"Loss in {name}.") == "Loss in PLACE_1."


# --- restoring -----------------------------------------------------------------


def test_unmask_distinguishes_place_1_from_place_10():
    names = [f"Nomé{i}" for i in range(1, 12)]
    masker = PlaceMasker(names)
    for name in names:
        masker.mask(name)
    assert masker.unmask("PLACE_1, PLACE_10, PLACE_11") == (
        "Nomé1, Nomé10, Nomé11"
    )


def test_unmask_handles_punctuation_and_possessives():
    masker = PlaceMasker(["Piauí"])
    masker.mask("Piauí")
    assert masker.unmask("PLACE_1's loss; (PLACE_1), PLACE_1.") == (
        "Piauí's loss; (Piauí), Piauí."
    )


def test_unmask_leaves_longer_ascii_tokens_alone():
    masker = PlaceMasker(["Piauí"])
    masker.mask("Piauí")
    assert masker.unmask("PLACE_1x xPLACE_1 PLACE_1_a PLACE_12") == (
        "PLACE_1x xPLACE_1 PLACE_1_a PLACE_12"
    )


def test_unmask_without_mapping_is_a_no_op():
    masker = PlaceMasker()
    assert masker.unmask("PLACE_1") == "PLACE_1"
    assert masker.unmask("") == ""


# --- safety --------------------------------------------------------------------


def test_stand_ins_skip_numbers_that_already_occur_in_the_input():
    text = "The text mentions PLACE_1 and Piauí."
    masker = PlaceMasker.for_texts(["Piauí"], text)
    assert masker.mask(text) == "The text mentions PLACE_1 and PLACE_2."
    # Only the stand-in it created is restored, never the genuine PLACE_1.
    assert masker.unmask("PLACE_1 and PLACE_2") == "PLACE_1 and Piauí"


def test_ascii_text_is_returned_untouched():
    masker = PlaceMasker(["Piauí"])
    text = "Tree cover loss in Brazil, 2020."
    assert masker.mask(text) is text


def test_punctuation_and_typographic_symbols_are_left_alone():
    masker = PlaceMasker(["Piauí", "Maranhão"])
    masked = _roundtrip(masker, "Piauí — Maranhão → “quoted” 3,600 ha")
    assert masked == "PLACE_1 — PLACE_2 → “quoted” 3,600 ha"
