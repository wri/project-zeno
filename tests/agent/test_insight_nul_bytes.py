"""Regression tests for control characters reaching ``insights.insight_text``.

Bug report: persisting an insight for an area whose name has an accented
character fails with::

    asyncpg.exceptions.CharacterNotInRepertoireError:
        invalid byte sequence for encoding "UTF8": 0x00

with the accented character replaced by NULs ("Paraná" -> "Par\\x00\\x00",
"Alto Rio Guamá" -> "Alto Rio Guam\\x00\\x00\\x00"). Postgres is right to
reject NULs in ``text``; the text must be cleaned before it is handed to
``persist_insight``.

The corruption is not limited to NUL. Gemini was also seen writing U+0003 in
place of "ã" ("Maranhão" -> "Maranh\\x03o"). Postgres accepts that, so it
would be stored and shown to users without any error. The tests therefore
check for control characters in general, not just ``\\x00``, and the "\\x03"
cases fail on their assertion rather than on a database error.

These run against the real test database, because the failure is Postgres /
asyncpg refusing the value, which a mocked session cannot show.

* ``test_raw_responses_*``: fixtures of what Gemini (``gemini-3-flash-preview``,
  structured output) actually returned: ``Piau\\u0000`` for "Piauí" (captured
  verbatim) and ``Maranh\\u0003o`` for "Maranhão" (rebuilt from the observed
  output; the wire form is assumed to be the JSON escape). The control
  character is in the model's output, not added by our code.
* ``test_text_generator_*``: the text stage against a model that reproduces
  that fault for every non-ASCII character it writes. Accented words are kept
  out of the prompt and restored in the response.
* ``test_persist_insight_*`` / ``test_update_insight_*``: the persistence
  boundary, the last line of defence. Whatever upstream stage corrupts the
  text, the write must not blow up and must not store control characters.
* ``test_analyze_*``: the full ``Analyst.analyze`` flow with a model that
  writes control characters on its own, so the whole path to the database is
  covered and the stored text matches what the agent is given.
* ``test_executor_parse_*``: guard that the Gemini executor parsing step
  itself keeps accented text intact, to narrow down where the NULs appear.
"""

import json
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import structlog.testing
from langchain_core.messages import AIMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.runnables import RunnableLambda
from sqlalchemy import select

from src.agent.subagents.analyst.charts.model import Insight, InsightChart
from src.agent.subagents.analyst.code_executors.base import (
    CodeActPart,
    PartType,
)
from src.agent.subagents.analyst.code_executors.gemini_executor import (
    GeminiCodeExecutor,
)
from src.agent.subagents.analyst.text_generator import (
    InsightText,
    InsightTextGenerator,
)
from src.agent.subagents.analyst.tool import Analyst
from src.api.data_models import InsightChartOrm, InsightOrm
from src.api.repositories.insight_writer import (
    persist_insight,
    update_insight,
)
from src.shared.request_context import bound_user_id
from tests.conftest import async_session_maker

# C0 control characters other than tab / newline / carriage return, and DEL:
# none of these belong in a narrative. Same set src.shared.text_sanitize strips.
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def assert_clean(text: str) -> None:
    found = CONTROL_CHARS.findall(text)
    assert not found, f"control characters {found!r} in {text!r}"


# (clean name, text as observed in the bug report / captured responses)
CORRUPTED_NAMES = [
    ("Paraná", "Par\x00\x00"),
    ("Alto Rio Guamá", "Alto Rio Guam\x00\x00\x00"),
    ("Piauí", "Piau\x00"),
    ("Maranhão", "Maranh\x03o"),
]

# Raw message text captured from gemini-3-flash-preview (structured output,
# finish_reason STOP). The model wrote the JSON escape \u0000 where "í" belongs.
CAPTURED_RAW_GEMINI_TEXT = (
    '{"primary_insight": "Piau\\u0000 has experienced a total of 3,600 ha of '
    "tree cover loss from 2021 to 2023. Annual loss peaked at 1,500 ha in "
    '2022 before decreasing to 900 ha in 2023.", '
    '"follow_up_suggestions": ["Investigate the specific regions within '
    'Piau\\u0000 experiencing the highest rates of tree cover loss.", '
    '"Analyze the drivers of the loss decrease observed between 2022 and 2023."]}'
)

# Rebuilt from the output seen in the probe run; Gemini replaced "ã" with U+0003.
RECONSTRUCTED_RAW_GEMINI_TEXT = (
    '{"primary_insight": "In Maranh\\u0003o, tree cover loss reached a total '
    "of 3,600 ha between 2021 and 2023. Annual loss increased from 1,200 ha "
    'in 2021 to a peak of 1,500 ha in 2022 before decreasing to 900 ha in 2023.", '
    '"follow_up_suggestions": ["Compare Maranh\\u0003o with a neighbouring state.", '
    '"Analyze the drivers of the loss decrease observed between 2022 and 2023."]}'
)

# (id, raw model text, control character the parsed text must not contain)
RAW_GEMINI_CASES = [
    pytest.param(CAPTURED_RAW_GEMINI_TEXT, "\x00", id="captured-piaui-nul"),
    pytest.param(
        RECONSTRUCTED_RAW_GEMINI_TEXT, "\x03", id="maranhao-etx-control-char"
    ),
]


class _ReplayModel:
    """Chat-model stand-in that replays a captured raw message.

    ``with_structured_output`` mirrors what LangChain does for JSON-mode
    structured output: the model's text goes through a Pydantic JSON parser,
    which is where ``\\u0000`` becomes a real NUL character.
    """

    def __init__(self, raw_text: str):
        self.raw_text = raw_text

    def with_structured_output(self, schema, **_kwargs):
        return RunnableLambda(
            lambda _prompt: AIMessage(content=self.raw_text)
        ) | PydanticOutputParser(pydantic_object=schema)


def _insight(primary_insight: str) -> Insight:
    return Insight(
        charts=[
            InsightChart(
                position=0,
                title="Annual tree cover loss",
                chart_type="bar",
                x_axis="year",
                y_axis="loss",
                chart_data=[{"year": 2020, "loss": 5}],
            )
        ],
        primary_insight=primary_insight,
        follow_up_suggestions=["Compare with a neighbouring area."],
    ).stamp_insight()


async def _stored_texts() -> list[str]:
    async with async_session_maker() as session:
        rows = (await session.execute(select(InsightOrm))).scalars().all()
    return [row.insight_text for row in rows]


@pytest.mark.parametrize("raw_text, char", RAW_GEMINI_CASES)
def test_raw_responses_really_contain_the_control_char(raw_text, char):
    """Sanity check on the fixtures: parsing the raw model text yields the real
    control character, as in the captured trace."""
    parsed = PydanticOutputParser(pydantic_object=InsightText).parse(raw_text)
    assert char in parsed.primary_insight


class _AccentGlitchModel:
    """Chat-model stand-in that reproduces the observed Gemini fault.

    It writes a short narrative about the area named in the user query and,
    like the real model, replaces every non-ASCII character it has to emit
    with a control character. It only ever sees the prompt it is given, so
    a prompt that keeps non-ASCII words out gives it nothing to corrupt.

    Assumption (to be confirmed by the probe script): the fault is triggered
    by accented words that appear in the prompt. Accents the model would
    produce on its own are not simulated.
    """

    def __init__(self, glitch_char: str = "\x03"):
        self.glitch_char = glitch_char
        self.prompts: list[str] = []

    def with_structured_output(self, schema, **_kwargs):
        def respond(prompt_value) -> AIMessage:
            prompt = prompt_value.to_string()
            self.prompts.append(prompt)
            area = re.search(r"## User query\nTree cover loss in (.+)", prompt)
            name = area.group(1).strip()
            broken = re.sub(r"[^\x00-\x7f]", self.glitch_char, name)
            return AIMessage(
                content=json.dumps(
                    {
                        "primary_insight": f"{broken} lost 3,600 ha in total.",
                        "follow_up_suggestions": [
                            f"Compare {broken} with a neighbouring area.",
                            "Analyze the drivers of the decrease.",
                        ],
                    }
                )
            )

        return RunnableLambda(respond) | PydanticOutputParser(
            pydantic_object=schema
        )


@pytest.mark.parametrize("glitch_char", ["\x00", "\x03"])
@pytest.mark.parametrize(
    "name", [clean for clean, _ in CORRUPTED_NAMES], ids=lambda n: n
)
async def test_text_generator_survives_the_accent_glitch(name, glitch_char):
    """Accented area names come back intact and free of control characters.

    The model corrupts any non-ASCII character it has to write. The text
    stage must keep accented words out of the prompt and restore them in the
    response, so the narrative reads "Piauí" and not "Piau\\x00".
    """
    model = _AccentGlitchModel(glitch_char)
    generator = InsightTextGenerator(model=model)

    result = await generator.generate(
        charts=[],
        dataset={},
        query=f"Tree cover loss in {name}",
        executor_context=f"Total loss in {name}: 3,600 ha",
    )

    assert_clean(result.primary_insight)
    for suggestion in result.follow_up_suggestions:
        assert_clean(suggestion)
    assert result.primary_insight == f"{name} lost 3,600 ha in total."
    assert result.follow_up_suggestions[0] == (
        f"Compare {name} with a neighbouring area."
    )
    # The prompt itself carried no accented characters from the data.
    assert "## User query" in model.prompts[0]
    data_section = model.prompts[0].split("## User query", 1)[1]
    assert data_section.isascii()


@pytest.mark.parametrize("clean, corrupted", CORRUPTED_NAMES)
async def test_persist_insight_with_control_chars_in_text(
    user, clean, corrupted
):
    """NULs must not make the INSERT fail, and control characters that
    Postgres would accept silently must not be stored either."""
    text = f"Tree cover loss in {corrupted} rose 12% over the period."

    # For the NUL cases this raises sqlalchemy.exc.DBAPIError wrapping
    # asyncpg CharacterNotInRepertoireError (invalid byte sequence ... 0x00).
    # For "\x03" the INSERT succeeds and the assertion below fails instead.
    insight_id = await persist_insight(
        _insight(text), user_id=user.id, thread_id="thread-1"
    )

    assert insight_id
    stored = await _stored_texts()
    assert len(stored) == 1
    assert_clean(stored[0])


@pytest.mark.parametrize(
    "suggestion", ["What about Par\x00\x00?", "What about Maranh\x03o?"]
)
async def test_persist_insight_with_control_chars_in_follow_ups(
    user, suggestion
):
    """Same rule for the other free-text field written next to the insight."""
    insight = _insight("Tree cover loss rose 12%.")
    insight.follow_up_suggestions = [suggestion]

    insight_id = await persist_insight(
        insight, user_id=user.id, thread_id="thread-1"
    )

    assert insight_id
    async with async_session_maker() as session:
        row = (await session.execute(select(InsightOrm))).scalars().one()
    for stored_suggestion in row.follow_up_suggestions:
        assert_clean(stored_suggestion)


@pytest.mark.parametrize(
    "raw_text, clean",
    [
        pytest.param(
            CAPTURED_RAW_GEMINI_TEXT, "Piauí", id="captured-piaui-nul"
        ),
        pytest.param(
            RECONSTRUCTED_RAW_GEMINI_TEXT, "Maranhão", id="maranhao-etx"
        ),
    ],
)
async def test_analyze_with_corrupted_model_output(user, raw_text, clean):
    """Full ``Analyst.analyze`` flow: executor -> text stage -> persist.

    The code executor is stubbed to return a chart for the accented area, and
    the text stage's model replays the raw message in which Gemini wrote a
    control character itself (it ignores the prompt, so sanitizing the input
    cannot help). The flow must still persist an insight, with no control
    characters in the stored text or in the text returned to the agent.
    """
    charts = [
        InsightChart(
            position=0,
            title=f"Tree cover loss in {clean}",
            chart_type="bar",
            x_axis="year",
            y_axis="loss",
            chart_data=[{"year": 2020, "loss": 5}],
        )
    ]
    statistics = [
        {
            "id": "stat-1",
            "dataset_id": "tree_cover_loss",
            "dataset_name": "Tree cover loss",
            "aoi_names": [clean],
            "aoi_ids": ["id-1"],
        }
    ]

    with (
        bound_user_id(user.id),
        patch.object(
            Analyst,
            "_resolve_charts",
            AsyncMock(return_value=(charts, [], f"{clean}: 5 ha", None)),
        ),
        patch(
            "src.agent.subagents.analyst.tool.InsightTextGenerator",
            lambda: InsightTextGenerator(model=_ReplayModel(raw_text)),
        ),
        patch(
            "src.agent.subagents.analyst.tool._build_tool_message",
            AsyncMock(return_value="ok"),
        ),
    ):
        command = await Analyst().analyze(
            query=f"Tree cover loss in {clean}",
            statistics=statistics,
            dataset={},
            tool_call_id="call-1",
        )

    # An error command (or an exception from persist_insight) means the
    # insight was lost: the user sees a failed analysis.
    assert command.update.get("insight_id"), command.update
    stored = await _stored_texts()
    assert len(stored) == 1
    assert_clean(stored[0])
    assert_clean(command.update["insight"])
    assert stored[0] == command.update["insight"]
    for suggestion in command.update["follow_up_suggestions"]:
        assert_clean(suggestion)


@pytest.mark.parametrize("clean, _corrupted", CORRUPTED_NAMES)
def test_executor_parse_keeps_accented_text(clean, _corrupted):
    """The executor's parsing must not mangle accented output (guard).

    Passes today: narrows the corruption to a later step or to the model's own
    output rather than ``GeminiCodeExecutor._parse_response``.
    """
    output = f"Total loss in {clean}: 5 ha"
    response = SimpleNamespace(
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(
                    parts=[
                        SimpleNamespace(
                            text=None,
                            executable_code=None,
                            code_execution_result=SimpleNamespace(
                                output=output
                            ),
                            inline_data=None,
                        )
                    ]
                )
            )
        ]
    )

    with patch.object(GeminiCodeExecutor, "__init__", lambda self: None):
        result = GeminiCodeExecutor()._parse_response(response)

    assert result.parts == [
        CodeActPart(type=PartType.EXECUTION_OUTPUT, content=output)
    ]
    assert_clean(result.parts[0].content)


async def test_persist_insight_with_control_chars_in_chart_fields(user):
    """Chart rows are LLM-written too, and JSONB rejects \\u0000 as well."""
    insight = Insight(
        charts=[
            InsightChart(
                position=0,
                title="Loss in Piau\x00",
                chart_type="bar",
                x_axis="place",
                y_axis="loss",
                chart_data=[{"place": "Maranh\x03o", "loss": 5}],
            )
        ],
        primary_insight="Tree cover loss rose 12%.",
        follow_up_suggestions=[],
    ).stamp_insight()

    await persist_insight(insight, user_id=user.id, thread_id="thread-1")

    async with async_session_maker() as session:
        chart = (
            (await session.execute(select(InsightChartOrm))).scalars().one()
        )
    assert chart.title == "Loss in Piau"
    assert chart.chart_data == [{"place": "Maranho", "loss": 5}]


@pytest.mark.parametrize("corrupted", ["Piau\x00", "Maranh\x03o"])
async def test_update_insight_with_control_chars(user, corrupted):
    """The restyle path writes LLM text too and gets the same protection."""
    async with async_session_maker() as session:
        row = InsightOrm(
            user_id=user.id,
            thread_id="thread-1",
            insight_text="Old summary.",
            follow_up_suggestions=[],
            statistics_ids=[],
            codeact_types=[],
            codeact_contents=[],
        )
        session.add(row)
        await session.commit()
        insight_id = row.id

    updated = await update_insight(
        str(insight_id),
        _insight(f"Loss in {corrupted} rose 12%."),
    )

    assert updated is True
    async with async_session_maker() as session:
        stored = await session.get(InsightOrm, insight_id)
    assert_clean(stored.insight_text)
    assert stored.insight_text.startswith("Loss in ")


async def test_persist_logs_what_it_strips(user):
    """The persistence backstop says which field it had to clean."""
    insight = _insight("Tree cover loss in Maranh\x03o rose.")
    insight.follow_up_suggestions = ["Compare Piau\x00."]

    with structlog.testing.capture_logs() as logs:
        await persist_insight(insight, user_id=user.id, thread_id="thread-1")

    fields = sorted(
        log["field"]
        for log in logs
        if log["event"] == "control_chars_stripped"
    )
    assert fields == ["follow_up_suggestion", "insight_text"]
