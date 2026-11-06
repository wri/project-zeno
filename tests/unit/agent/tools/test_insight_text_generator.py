"""Unit tests for InsightTextGenerator.

The LLM chain is replaced with a fake runnable so these are hermetic; they
assert the prompt is grounded in chart data + dataset cautions/presentation and
honors the wording guide.
"""

import pytest
import structlog.testing

from src.agent.subagents.analyst.charts.model import InsightChart
from src.agent.subagents.analyst.text_generator import (
    InsightText,
    InsightTextGenerator,
)


class _FakeChain:
    """Captures inputs passed to ainvoke; returns a fixed InsightText."""

    def __init__(self):
        self.last_inputs = None
        self.last_config = None

    def with_config(self, **kwargs):
        return self

    async def ainvoke(self, inputs, config=None):
        self.last_inputs = inputs
        self.last_config = config
        return InsightText(
            primary_insight="Loss increased.",
            follow_up_suggestions=["Compare regions."],
        )


@pytest.fixture
def generator(monkeypatch):
    gen = InsightTextGenerator.__new__(InsightTextGenerator)
    fake = _FakeChain()
    gen._chain = fake
    return gen, fake


CHARTS = [
    InsightChart(
        position=0,
        title="Annual Loss",
        chart_type="bar",
        x_axis="year",
        y_axis="area_ha",
        chart_data=[{"year": 2020, "area_ha": 1234.5}],
    )
]
DATASET = {
    "cautions": "Tree cover loss is not deforestation.",
    "presentation_instructions": "Use neutral wording.",
}


@pytest.mark.asyncio
async def test_generate_returns_structured_text(generator):
    gen, _ = generator
    result = await gen.generate(CHARTS, DATASET, query="Loss in Brazil?")
    assert result.primary_insight == "Loss increased."
    assert result.follow_up_suggestions == ["Compare regions."]


@pytest.mark.asyncio
async def test_generate_passes_executor_context(generator):
    gen, fake = generator
    context = "High total: 1306617.82 ha\nHighest total: 12982.53 ha"
    await gen.generate(
        CHARTS, DATASET, query="Loss?", executor_context=context
    )
    assert fake.last_inputs["executor_context"] == context


@pytest.mark.asyncio
async def test_generate_defaults_executor_context(generator):
    gen, fake = generator
    await gen.generate(CHARTS, DATASET, query="Loss?")
    assert fake.last_inputs["executor_context"] == "(none)"


@pytest.mark.asyncio
async def test_prompt_includes_cautions_and_presentation(generator):
    gen, fake = generator
    await gen.generate(CHARTS, DATASET, query="Loss in Brazil?")
    inputs = fake.last_inputs
    assert inputs["cautions"] == "Tree cover loss is not deforestation."
    assert inputs["presentation_instructions"] == "Use neutral wording."
    assert "Wording" in inputs["wording_guide"]


@pytest.mark.asyncio
async def test_prompt_serializes_chart_data(generator):
    gen, fake = generator
    await gen.generate(CHARTS, DATASET, query="Loss in Brazil?")
    charts_block = fake.last_inputs["charts"]
    assert "Annual Loss" in charts_block
    assert "year" in charts_block and "area_ha" in charts_block
    assert "1234.5" in charts_block
    # serialized as JSON, and the per-chart narrative field is excluded
    assert "chart_type" in charts_block
    assert "insight" not in charts_block


@pytest.mark.asyncio
async def test_config_is_forwarded_to_chain(generator):
    gen, fake = generator
    cfg = {"callbacks": ["x"]}
    await gen.generate(CHARTS, DATASET, query="q", config=cfg)
    assert fake.last_config == cfg


# --- non-ASCII words are kept out of the prompt ---------------------------


class _EchoChain(_FakeChain):
    """Answers with the stand-ins it was given, as a model that copies the
    place tokens from the prompt would."""

    async def ainvoke(self, inputs, config=None):
        self.last_inputs = inputs
        return InsightText(
            primary_insight="PLACE_1 lost 3,600 ha; PLACE_2 lost 10 ha.",
            follow_up_suggestions=["Why did PLACE_1 change?"],
        )


def _echo_generator():
    gen = InsightTextGenerator.__new__(InsightTextGenerator)
    gen._chain = chain = _EchoChain()
    return gen, chain


@pytest.mark.asyncio
async def test_place_names_are_masked_in_prompt_and_restored():
    gen, chain = _echo_generator()
    charts = [
        InsightChart(
            position=0,
            title="Perda de cobertura em Piauí",
            chart_type="bar",
            x_axis="year",
            y_axis="area_ha",
            chart_data=[{"year": 2020, "area_ha": 1.0}],
        )
    ]

    result = await gen.generate(
        charts,
        {"cautions": "Dados de São Paulo são estimativas."},
        query="Perda em Piauí",
        executor_context="Piauí: 3,600 ha",
        place_names=["Piauí", "São Paulo"],
    )

    sent = chain.last_inputs
    # Data fields never carry a non-ASCII place name...
    assert sent["charts"].isascii()
    assert sent["executor_context"].isascii()
    assert sent["query"] == "Perda em PLACE_1"
    assert sent["cautions"] == "Dados de PLACE_2 são estimativas."
    # ...and prose that is not a place name is left readable.
    assert "são" in sent["cautions"]
    assert (
        result.primary_insight == "Piauí lost 3,600 ha; São Paulo lost 10 ha."
    )
    assert result.follow_up_suggestions == ["Why did Piauí change?"]


@pytest.mark.asyncio
async def test_words_that_are_not_listed_area_names_are_left_alone():
    gen, chain = _echo_generator()

    await gen.generate(
        CHARTS,
        DATASET,
        query="Perda em Marabá no último ano",
        executor_context="Marabá: 3,600 ha",
        place_names=["Piauí"],
    )

    # Only listed area names are masked; everything else is sent as written.
    assert chain.last_inputs["query"] == "Perda em Marabá no último ano"
    assert chain.last_inputs["executor_context"] == "Marabá: 3,600 ha"
    assert chain.last_inputs["place_note"] == ""


class _ScriptedChain(_FakeChain):
    """Answers with a fixed narrative, as a model that wrote it from the
    prompt would."""

    def __init__(self, narrative: str):
        super().__init__()
        self.narrative = narrative

    async def ainvoke(self, inputs, config=None):
        self.last_inputs = inputs
        return InsightText(
            primary_insight=self.narrative,
            follow_up_suggestions=["Comparar PLACE_1 com outra área."],
        )


def _scripted_generator(narrative: str):
    gen = InsightTextGenerator.__new__(InsightTextGenerator)
    gen._chain = chain = _ScriptedChain(narrative)
    return gen, chain


@pytest.mark.asyncio
async def test_portuguese_para_and_e_are_never_rewritten():
    gen, chain = _scripted_generator(
        "O PLACE_1 perdeu 3.600 ha entre 2021 e 2023. "
        "Para comparar, a perda caiu."
    )

    result = await gen.generate(
        CHARTS,
        DATASET,
        query="Qual é o desmatamento no Pará?",
        executor_context="Total loss in Pará: 3,600 ha",
        place_names=["Pará"],
    )

    assert chain.last_inputs["query"] == "Qual é o desmatamento no PLACE_1?"
    assert result.primary_insight == (
        "O Pará perdeu 3.600 ha entre 2021 e 2023. "
        "Para comparar, a perda caiu."
    )
    assert result.follow_up_suggestions == ["Comparar Pará com outra área."]


@pytest.mark.asyncio
async def test_spanish_esta_and_pérdida_are_never_rewritten():
    gen, chain = _scripted_generator(
        "esta región muestra una pérdida de 9 ha en PLACE_1; está claro."
    )

    result = await gen.generate(
        CHARTS,
        DATASET,
        query="¿Cómo está la pérdida de bosque en Perú?",
        place_names=["Perú"],
    )

    assert chain.last_inputs["query"] == (
        "¿Cómo está la pérdida de bosque en PLACE_1?"
    )
    assert result.primary_insight == (
        "esta región muestra una pérdida de 9 ha en Perú; está claro."
    )


@pytest.mark.asyncio
async def test_non_latin_queries_reach_the_model_unchanged_but_for_the_name():
    cases = [
        (
            "Московская область",
            "Сколько леса потеряла Московская область в 2023 году?",
            "Сколько леса потеряла PLACE_1 в 2023 году?",
        ),
        (
            "云南省",
            "中国云南省2023年的森林损失是多少？",
            "中国PLACE_1 2023年的森林损失是多少？",
        ),
        (
            "الجزائر",
            "كم فقدت الجزائر من الغطاء الشجري في عام 2023؟",
            "كم فقدت PLACE_1 من الغطاء الشجري في عام 2023؟",
        ),
        (
            "उत्तराखंड",
            "2023 में उत्तराखंड ने कितना वन खोया?",
            "2023 में PLACE_1 ने कितना वन खोया?",
        ),
    ]
    for name, query, expected in cases:
        gen, chain = _scripted_generator("PLACE_1")
        await gen.generate(CHARTS, DATASET, query=query, place_names=[name])
        assert chain.last_inputs["query"] == expected, name


@pytest.mark.asyncio
async def test_chinese_name_directly_followed_by_text_is_restored():
    gen, _ = _scripted_generator("PLACE_1的森林损失在2023年为12公顷")

    result = await gen.generate(
        CHARTS,
        DATASET,
        query="中国云南省2023年的森林损失是多少？",
        place_names=["云南省"],
    )

    assert result.primary_insight == "云南省的森林损失在2023年为12公顷"


@pytest.mark.asyncio
async def test_localised_chart_text_stays_readable_in_the_prompt():
    gen, chain = _echo_generator()
    charts = [
        InsightChart(
            position=0,
            title="Потеря лесного покрова: Московская область",
            chart_type="bar",
            x_axis="Год",
            y_axis="Площадь (га)",
            series_fields=["Естественный лес", "Плантации"],
            chart_data=[{"Год": 2021, "Естественный лес": 120}],
        )
    ]

    await gen.generate(
        charts,
        DATASET,
        query="Сколько леса потеряла Московская область?",
        place_names=["Московская область"],
    )

    sent = chain.last_inputs["charts"]
    # The chart's own wording is untouched; only the area's name is masked.
    for text in ("Потеря лесного покрова", "Год", "Площадь (га)", "Плантации"):
        assert text in sent
    assert "Московская область" not in sent
    assert sent.count("PLACE_1") == 1
    assert sent.count("PLACE_") == 1


@pytest.mark.asyncio
async def test_prompt_note_is_added_only_when_names_were_masked():
    gen, chain = _echo_generator()

    await gen.generate(CHARTS, DATASET, query="Loss in Brazil?")
    assert chain.last_inputs["place_note"] == ""

    await gen.generate(
        CHARTS, DATASET, query="Loss in Piauí?", place_names=["Piauí"]
    )
    assert "PLACE_1" in chain.last_inputs["place_note"]


@pytest.mark.asyncio
async def test_ascii_place_names_are_not_masked():
    gen, chain = _echo_generator()
    await gen.generate(
        CHARTS, DATASET, query="Loss in Brazil?", place_names=["Brazil"]
    )
    assert chain.last_inputs["query"] == "Loss in Brazil?"
    assert chain.last_inputs["place_note"] == ""


@pytest.mark.asyncio
async def test_system_prompt_inputs_are_not_sanitized(generator):
    gen, fake = generator
    await gen.generate(CHARTS, DATASET, query="Perda em Piauí", language="pt")
    # The language name tells the model what to write in; it must stay intact.
    assert fake.last_inputs["language"] == "Português"


class _GlitchedChain(_FakeChain):
    """A model that writes control characters on its own, with no accented
    word in the prompt to blame (e.g. a Portuguese narrative)."""

    async def ainvoke(self, inputs, config=None):
        self.last_inputs = inputs
        return InsightText(
            primary_insight="A previs\x03o para o Piau\x00 melhorou.",
            follow_up_suggestions=["Compare com Maranh\x03o."],
        )


@pytest.mark.asyncio
async def test_control_characters_the_model_writes_itself_are_stripped():
    gen = InsightTextGenerator.__new__(InsightTextGenerator)
    gen._chain = _GlitchedChain()

    with structlog.testing.capture_logs() as logs:
        result = await gen.generate(
            CHARTS, DATASET, query="Loss?", language="pt"
        )

    assert result.primary_insight == "A previso para o Piau melhorou."
    assert result.follow_up_suggestions == ["Compare com Maranho."]
    # Stripping is logged, tagged with the field it happened in, so a rise in
    # model-written control characters shows up in the logs.
    stripped = [
        log for log in logs if log["event"] == "control_chars_stripped"
    ]
    assert [(log["log_level"], log["field"]) for log in stripped] == [
        ("warning", "text_stage.primary_insight"),
        ("warning", "text_stage.follow_up_suggestion"),
    ]
    assert all(log["count"] >= 1 and log["codepoints"] for log in stripped)
