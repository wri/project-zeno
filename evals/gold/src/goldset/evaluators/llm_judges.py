import os
import re
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from openrouter import OpenRouter
from pydantic import BaseModel

from goldset.evaluators.chart_numeric import (
    evaluate_numeric_support,
    format_number,
    parse_expected_number,
)
from goldset.judge_config import (
    JUDGE_BACKEND_OPENROUTER_JEV,
    OPENROUTER_JEV_MODEL,
    resolve_judge_backend,
)
from goldset.models import HAIKU

# Relative tolerance for numeric answers, as a fraction of the expected value.
# Interpolated into the prompt so the threshold and its worked examples cannot drift.
#
# Neither judge does the arithmetic: their own comparisons were unreliable, even on
# identical input. For charts, `chart_numeric` compares the expected figure with the
# chart's own data. For prose answers, the judge only copies out the figure that
# answers the question and `resolve_answer_verdict` compares it. Both apply this
# tolerance in code. The prose parser cannot read every language's number format, so
# there a judge PASS can override a deterministic FAIL (see `resolve_answer_verdict`).
NUMERIC_TOLERANCE = 0.02
_TOLERANCE_PCT = f"{NUMERIC_TOLERANCE:.0%}"

_NUMERIC_CANDIDATE_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?(?:\s*[%A-Za-z²]+)?")
_NUMERIC_CANDIDATE_MAX = 12

# Numeric scoring rules for the answer judge. Kept at module level, and free of `{}` so
# it can be concatenated into a ChatPromptTemplate without being read as a placeholder,
# and so tests can assert on it without an API call.
_NUMERIC_RULES = f"""
                **NUMERIC** (numbers with optional units):
                - Expected answer contains numbers: "198.4 hectares", "0.20%", "211 kha", "924,000 km²"
                - **Extraction rule**: Identify THE main answer number (usually stated as "total", "X hectares were", or the first/most prominent number directly answering the question) — not a breakdown/detail number.
                  - Example: "A total of 231.97 hectares were affected. Short vegetation had 176.36 ha..." → the main number is 231.97, not 176.36
                - Copy that number into `extracted_number` **exactly as written** in the actual answer, including its unit and sign (e.g. "200 hectares", "-286,994 Mg CO2e", "0.19%"). Do not convert units or round it — a deterministic check normally applies the {_TOLERANCE_PCT} tolerance to `extracted_number` in code instead of you computing it.
                - Still give `score` your own careful best judgement of whether the actual value matches the expected value (roughly {_TOLERANCE_PCT} or closer counts as a match) — use your understanding of the actual answer's language and numeric conventions (a decimal comma in French/German/Indonesian text, a non-English scale word, etc.). The deterministic check above cannot read those conventions, so when it disagrees with a PASS from you, your score is trusted instead — a mismatch there is usually the parser misreading the number, not the agent being wrong. A FAIL from you never overrides a deterministic PASS.
                - Leave `extracted_number` as an empty string for every answer type other than NUMERIC.
"""

ANSWER_JUDGE_PROMPT = (
    """
                You are evaluating if an AI-generated insight captures the essence of an expected answer.

                EXPECTED ANSWER: {expected_answer}

                ACTUAL INSIGHT: {actual_answer}

                Your task is to:
                1. Detect the answer type
                2. Apply the appropriate comparison logic
                3. Return a score (0 or 1)

                ## Answer Type Detection & Scoring Rules

                **BOOLEAN** (true/false, yes/no questions):
                - Expected answer contains: "TRUE", "FALSE", "True", "False", "true", "false", "yes", "no", "Yes", "No"
                - Scoring: Exact semantic match required
                - **First, extract the boolean value from the actual answer** (usually at the start: "True", "False", "yes", "no")
                - **Then compare**: TRUE matches with yes/true/affirmative, FALSE matches with no/false/negative
                - Examples:
                  - Expected "TRUE" vs Actual "true" → MATCH (1)
                  - Expected "TRUE" vs Actual "yes" → MATCH (1)
                  - Expected "TRUE" vs Actual "False." → NO MATCH (0) [opposite values]
                  - Expected "TRUE" vs Actual "no" → NO MATCH (0) [opposite values]
                  - Expected "FALSE" vs Actual "TRUE" → NO MATCH (0) [opposite values]
                  - Expected "FALSE" vs Actual "false" → MATCH (1)
                  - Expected "TRUE" vs Actual "The statement is correct" → MATCH (1) [affirms without explicit FALSE]
                - **CRITICAL**: If the actual answer contains "False", "false", "no", or "No", it CANNOT match "TRUE". Vice versa.
"""
    + _NUMERIC_RULES
    + """
                **YEAR** (4-digit years):
                - Expected answer is a year: "2015", "2023"
                - Scoring: Exact match required
                - Examples:
                  - Expected "2015" vs Actual "2015" → MATCH (1)
                  - Expected "2015" vs Actual "2016" → NO MATCH (0)

                **NAMED_ENTITY** (countries, regions, places, land cover types):
                - Expected answer is a proper noun or descriptive term: "Brazil", "South Dakota"
                - Scoring: Semantic similarity - the actual answer should clearly identify the same entity or category
                - Examples:
                  - Expected "Brazil" vs Actual "Brazil had the most" → MATCH (1)
                  - Expected "South Dakota" vs Actual "S Dakota" → MATCH (1)
                  - Expected "Brazil" vs Actual "Australia" → NO MATCH (0)

                ## Instructions

                1. First, identify which answer_eval_type the expected answer belongs to
                2. Apply the appropriate scoring rule from above
                3. Return:
                   - score: 1 if it matches according to the rules, 0 if it does not
                   - reason: one concise sentence explaining why you gave that score
                   - answer_eval_type: one of "boolean", "numeric", "year", "named_entity"
                   - extracted_number: for NUMERIC answers only, the main answer number
                     copied verbatim from the actual answer (see the NUMERIC rules above);
                     an empty string for every other answer_eval_type

                Be strict with the rules above, especially for boolean, numeric, and year types.
                """
)


class JudgeError(RuntimeError):
    """An LLM judge call failed. Raised instead of guessing a verdict, so a
    judge outage is reported as an error, never as a score."""

    def __init__(self, check: str, cause: Exception):
        super().__init__(f"{check}: {cause}")
        self.check = check


def _using_openrouter_decisions() -> bool:
    return resolve_judge_backend() == JUDGE_BACKEND_OPENROUTER_JEV


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        if isinstance(dumped, dict):
            return dumped
    if hasattr(value, "to_dict"):
        dumped = value.to_dict()
        if isinstance(dumped, dict):
            return dumped
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    raise RuntimeError(f"cannot read structured decision output: {type(value)!r}")


def _openrouter_answers(
    *,
    check: str,
    questions: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set for OpenRouter judge mode")

    with OpenRouter(api_key=api_key) as open_router:
        response = open_router.alpha.decisions.create(
            model=OPENROUTER_JEV_MODEL,
            questions=questions,
            state=state,
        )

    answers = _as_dict(response).get("answers")
    if answers is None:
        raise RuntimeError(f"{check}: decisions response omitted answers")
    if isinstance(answers, dict):
        return answers
    if hasattr(answers, "items"):
        return dict(answers.items())
    raise RuntimeError(f"{check}: cannot decode answers payload ({type(answers)!r})")


def _answer_field(answer: Any, field: str) -> Any:
    if isinstance(answer, dict):
        return answer.get(field)
    return getattr(answer, field, None)


def _noul_to_score(noul: Any, *, check: str) -> float:
    if isinstance(noul, bool):
        return 1.0 if noul else 0.0
    if isinstance(noul, int | float):
        return float(noul)
    raise RuntimeError(f"{check}: expected a numeric noul answer, got {noul!r}")


def _openrouter_binary_judgement(
    *,
    check: str,
    instructions: str,
    state: dict[str, Any],
) -> tuple[int, str]:
    answers = _openrouter_answers(
        check=check,
        questions={
            "decision": {
                "type": "noul",
                "instructions": instructions,
                "criteria": {
                    "true": "The statement is true.",
                    "false": "The statement is false.",
                },
            }
        },
        state=state,
    )
    decision = answers.get("decision")
    if decision is None:
        raise RuntimeError(f"{check}: missing decision answer")
    noul = _noul_to_score(_answer_field(decision, "noul"), check=check)
    score = 1 if noul >= 0.5 else 0
    reason = (
        f"OpenRouter Decisions ({OPENROUTER_JEV_MODEL}) noul={noul:.2f}; "
        f"mapped to score={score}"
    )
    return score, reason


def _numeric_extraction_candidates(text: str) -> list[str]:
    """Candidate numeric snippets as written in the answer text.

    OpenRouter Decisions' choice question can then select which candidate is
    the primary answer number, preserving deterministic tolerance gating in
    `resolve_answer_verdict`.
    """
    candidates: list[str] = []
    for match in _NUMERIC_CANDIDATE_RE.finditer(text or ""):
        token = match.group(0).strip().rstrip(",.;:)")
        if token and token not in candidates:
            candidates.append(token)
        if len(candidates) >= _NUMERIC_CANDIDATE_MAX:
            break
    return candidates


def llm_judge_clarification(agent_state: dict, query: str) -> dict:
    """Ask the judge whether the agent asked for clarification instead of
    attempting the task."""

    class ClarificationJudgment(BaseModel):
        # Reasoning comes before the verdict: Haiku commits to the first field
        # it emits, so a verdict written first can contradict its own reasoning.
        explanation: str
        is_clarification: bool

    # The response is the first chart's insight, else the last message.
    charts_data = agent_state.get("charts_data", [])
    final_response = ""

    if charts_data:
        final_response = charts_data[0].get("insight", "")

    if not final_response:
        messages = agent_state.get("messages", [])

        if messages:
            content = messages[-1].content

            if isinstance(content, str):
                # Claude format: direct string
                final_response = content
            elif isinstance(content, list) and content:
                # Gemini format: list of content items
                last_item = content[-1]
                if isinstance(last_item, dict) and "text" in last_item:
                    final_response = last_item["text"]
                else:
                    # Fallback for unexpected list items
                    final_response = str(last_item)
            else:
                # Fallback for any other format
                final_response = str(content) if content else ""
        else:
            final_response = ""

    if not final_response:
        return {"is_clarification": False, "explanation": "No response to evaluate"}

    if _using_openrouter_decisions():
        try:
            score, reason = _openrouter_binary_judgement(
                check="clarification_requested",
                instructions=(
                    "Decide whether the AGENT_RESPONSE is primarily asking for "
                    "clarification or more information before it can answer the "
                    "ORIGINAL_QUERY."
                ),
                state={
                    "original_query": query,
                    "agent_response": final_response,
                },
            )
            return {
                "is_clarification": bool(score),
                "explanation": reason,
            }
        except Exception as error:
            raise JudgeError("clarification_requested", error) from error

    CLARIFICATION_JUDGE_PROMPT = ChatPromptTemplate.from_messages(
        [
            (
                "user",
                """
            You are evaluating whether an AI agent is asking for clarification instead of completing a task.

            ORIGINAL QUERY: {query}

            AGENT RESPONSE: {response}

            Does the agent response indicate that it's asking for clarification, more information, or unable to proceed due to ambiguity in the original query?

            Signs of clarification requests:
            - Asking questions back to the user
            - Requesting more specific information
            - Indicating multiple possible interpretations
            - Asking to choose between options
            - Expressing uncertainty about what the user wants

            Do NOT count the response as a clarification request if the agent directly answers the user's question
            and only asks an optional follow-up question afterward, such as offering to analyze a specific region,
            compare locations, or continue with a next step.

            Only return true if the response primarily asks for more information before it can answer,
            or says it cannot proceed because the original query is ambiguous.

            Return true if this is a clarification request, false if the agent attempted to complete the task.
            """,
            ),
        ],
    )

    judge_chain = CLARIFICATION_JUDGE_PROMPT | HAIKU.with_structured_output(
        ClarificationJudgment,
    )

    try:
        result = judge_chain.invoke({"query": query, "response": final_response})
        return result.model_dump()
    except Exception as error:
        # Never fall back to False: on a case expecting no clarification, that
        # would score a judge outage as a pass.
        raise JudgeError("clarification_requested", error) from error


def resolve_answer_verdict(
    answer_eval_type: str,
    expected_answer: str,
    extracted_number: str,
    judge_reason: str,
    judge_score: int,
) -> dict[str, Any]:
    """Combine the deterministic numeric check with the judge's own score.

    The check uses the same ``NUMERIC_TOLERANCE`` and ``parse_expected_number``
    as the chart comparator, so an answer and its chart agree on what "within
    tolerance" means. A deterministic PASS is final.

    A deterministic FAIL is not. The parser reads only English scale words and
    ``.`` as the decimal separator, so it misreads answers such as "61.19万公顷"
    (万 is the Chinese scale word for 10,000) or "289,11 hectares" (a French
    decimal comma). On a deterministic FAIL, a judge PASS wins, because the judge
    read the prose in its own language.

    Falls back to the judge's score and reason when the check cannot run: a
    non-numeric case, an empty extraction, a number that fails to parse on either
    side, or a percentage on one side only.
    """
    if answer_eval_type != "numeric" or not extracted_number:
        return {"score": judge_score, "reason": judge_reason}

    expected = parse_expected_number(expected_answer)
    actual = parse_expected_number(extracted_number)
    if expected is None or actual is None or expected.is_percent != actual.is_percent:
        return {"score": judge_score, "reason": judge_reason}

    difference = abs(actual.value - expected.value) / abs(expected.value)
    within = difference <= NUMERIC_TOLERANCE
    unit = "%" if expected.is_percent else ""
    deterministic_reason = (
        f"deterministic check: expected {format_number(expected.value)}{unit}, "
        f"extracted {format_number(actual.value)}{unit} from \"{extracted_number}\", "
        f"a {difference:.2%} difference, "
        f"{'within' if within else 'exceeding'} the {_TOLERANCE_PCT} tolerance"
    )
    if within:
        return {"score": 1, "reason": deterministic_reason}

    if judge_score == 1:
        return {
            "score": 1,
            "reason": (
                f"{deterministic_reason} — overriding the deterministic check "
                f"(locale-blind number parsing): the judge read the actual "
                f"answer and says it matches: {judge_reason}"
            ),
        }
    return {"score": 0, "reason": f"{deterministic_reason}. {judge_reason}"}


class AnswerJudgement(BaseModel):
    answer_eval_type: str  # "boolean", "numeric", "named_entity", "year"
    reason: str
    score: int
    extracted_number: str = ""  # numeric rows only; see resolve_answer_verdict


def judge_answer(expected_answer: str, actual_answer: str) -> AnswerJudgement:
    """The raw answer-judge call, before any deterministic override."""
    JUDGE_PROMPT = ChatPromptTemplate.from_messages([("user", ANSWER_JUDGE_PROMPT)])
    judge_chain = JUDGE_PROMPT | HAIKU.with_structured_output(AnswerJudgement)
    return judge_chain.invoke(
        {
            "expected_answer": expected_answer,
            "actual_answer": actual_answer,
        },
    )


def llm_judge(
    expected_answer: str,
    actual_answer: str,
    include_reason: bool = False,
):
    """Use LLM to judge if an actual answer captures the essence of an expected answer."""

    if _using_openrouter_decisions():
        answers = _openrouter_answers(
            check="agent_answer",
            questions={
                "answer_eval_type": {
                    "type": "choice",
                    "instructions": (
                        "Classify EXPECTED_ANSWER as boolean, numeric, year, "
                        "or named_entity."
                    ),
                    "criteria": {
                        "boolean": "true/false or yes/no expectation",
                        "numeric": "expects a number, possibly with a unit",
                        "year": "expects a 4-digit year",
                        "named_entity": "expects a place, category, or term",
                    },
                },
                "matches": {
                    "type": "noul",
                    "instructions": (
                        "Determine whether ACTUAL_INSIGHT matches "
                        "EXPECTED_ANSWER. Use semantic and factual consistency "
                        "without doing deterministic tolerance arithmetic."
                    ),
                    "criteria": {
                        "true": "Actual insight matches expected answer.",
                        "false": "Actual insight does not match expected answer.",
                    },
                },
            },
            state={
                "expected_answer": expected_answer,
                "actual_insight": actual_answer,
            },
        )
        eval_answer = answers.get("answer_eval_type")
        match_answer = answers.get("matches")
        if eval_answer is None or match_answer is None:
            raise RuntimeError("agent_answer: missing answer_eval_type or matches")
        answer_eval_type = _answer_field(eval_answer, "choice") or "named_entity"
        if answer_eval_type not in {"boolean", "numeric", "named_entity", "year"}:
            answer_eval_type = "named_entity"

        extracted_number = ""
        if answer_eval_type == "numeric":
            candidates = _numeric_extraction_candidates(actual_answer)
            if candidates:
                option_keys = [f"option_{idx + 1}" for idx in range(len(candidates))]
                extraction_answers = _openrouter_answers(
                    check="agent_answer",
                    questions={
                        "extracted_number_choice": {
                            "type": "choice",
                            "instructions": (
                                "Select the option that is the main number in "
                                "ACTUAL_INSIGHT directly answering "
                                "EXPECTED_ANSWER. Prefer totals over breakdown "
                                "numbers."
                            ),
                            "criteria": {
                                key: (
                                    "Use this when the main answer number is "
                                    f"exactly: {candidate}"
                                )
                                for key, candidate in zip(option_keys, candidates)
                            },
                        }
                    },
                    state={
                        "expected_answer": expected_answer,
                        "actual_insight": actual_answer,
                    },
                )
                choice_answer = extraction_answers.get("extracted_number_choice")
                choice_key = _answer_field(choice_answer, "choice")
                if isinstance(choice_key, str):
                    option_map = dict(zip(option_keys, candidates))
                    extracted_number = option_map.get(choice_key, "")

        noul = _noul_to_score(_answer_field(match_answer, "noul"), check="agent_answer")
        judge_score = 1 if noul >= 0.5 else 0
        confidence = _answer_field(match_answer, "confidence")
        if isinstance(confidence, int | float):
            confidence_text = f", confidence={float(confidence):.2f}"
        else:
            confidence_text = ""
        judge_reason = (
            f"OpenRouter Decisions ({OPENROUTER_JEV_MODEL}) "
            f"type={answer_eval_type}, noul={noul:.2f}{confidence_text}"
        )
        llm_judgement = AnswerJudgement(
            answer_eval_type=answer_eval_type,
            score=judge_score,
            reason=judge_reason,
            extracted_number=extracted_number,
        )
    else:
        llm_judgement = judge_answer(expected_answer, actual_answer)

    verdict = resolve_answer_verdict(
        answer_eval_type=llm_judgement.answer_eval_type,
        expected_answer=expected_answer,
        extracted_number=llm_judgement.extracted_number,
        judge_score=llm_judgement.score,
        judge_reason=llm_judgement.reason,
    )

    if include_reason:
        return verdict

    return verdict["score"]


def resolve_chart_verdict(
    judge_score: int | float | None,
    judge_reason: str,
    support: str | None,
    explanation: str,
) -> dict[str, Any]:
    """Combine the deterministic comparator and the chart judge into one verdict.

    The comparator decides; the judge's score is recorded but never gates. The
    judge's opinion of a chart's framing flipped between identical trials while
    the comparator's verdict did not, and ``cases/README.md`` rules out failing a
    case on chart choice.

    ``unsupported`` -> 0.0   the chart's data does not contain the figure
    ``supported``   -> 1.0   it does; any objection from the judge is info-only
    ``None``        -> None  no numeric claim to check (a yes/no answer or a
                             place name), so ``charts_answer`` is not scored
    """
    judge = None if judge_score is None else float(judge_score)

    if support == "unsupported":
        score: float | None = 0.0
        if judge == 0.0:
            reason = f"{explanation}. {judge_reason}"
        else:
            reason = (
                f"{explanation} — overriding the judge (info-only), "
                f"which said: {judge_reason}"
            )
    elif support == "supported":
        score = 1.0
        if judge == 0.0:
            reason = (
                f"{explanation} — the judge (info-only) disagreed on framing: "
                f"{judge_reason}"
            )
        else:
            reason = f"{explanation}. {judge_reason}"
    else:
        score = None
        reason = (
            "no numeric claim to check deterministically; not scored. "
            f"Judge (info-only) said: {judge_reason}"
        )

    return {"score": score, "reason": reason, "judge_score": judge}


def llm_judge_chart(
    query: str,
    expected_answer: str,
    charts_json: str,
    codeact_summary: str = "",
    include_reason: bool = False,
) -> int | dict[str, int | str]:
    """Score a case's charts: code decides, the judge's view is recorded.

    The judge sees the chart JSON array (plus a summary of the code the agent ran
    and its output, when there is one) and says whether the charts together suit
    the query. Its score is returned as ``judge_score`` and is info-only. The
    returned ``score`` is whether the chart data contains the expected figure
    (``evaluate_numeric_support``); see ``resolve_chart_verdict``.
    """

    class ChartScore(BaseModel):
        reason: str
        score: int

    codeact_section = ""
    codeact_instruction = ""
    if codeact_summary:
        codeact_section = """

CODEACT REASONING:
{codeact_summary}

This shows the code the agent executed, the intermediate results, and its
analytical reasoning that led to the chart(s) above."""
        codeact_instruction = """

If codeact reasoning is provided, use it to cross-check the chart data.
If the code shows correct data processing but the chart specification has
wrong metrics, filters, or structure, score 0 because the chart itself is
flawed. If the code reveals incorrect analysis (e.g., wrong aggregation,
wrong data source) even if the chart specification looks plausible on its
own, also score 0.

"""

    full_prompt = (
        """You are evaluating whether one or more chart specifications are useful and correct for answering a user query.

USER QUERY:
{query}

EXPECTED ANSWER:
{expected_answer}

CHART JSON (JSON array of chart objects):
{charts_json}"""
        + codeact_section
        + """

The input is a JSON array of chart objects. There may be one chart or multiple.
Evaluate whether the set of charts together answers the user's query.

Score 1 if the chart(s) together appear appropriate for the query and their
encoded data, chart types, labels, dimensions, measures, filters, and time
ranges would help a user verify or understand the expected answer.

Score 0 if the chart(s) are missing important data, use the wrong
metric/location/date range, have unsuitable chart types for the comparison,
report a different quantity or category from the one asked for, or are too
incomplete to judge.

Do not score based on any prose insight or narrative answer. Focus on the
chart specifications, encoded data, labels, fields, and visual structures.

NUMERIC AGREEMENT IS NOT YOUR JOB. Whether the chart's figures match the
expected answer's figures is checked separately, in code, against the chart's
own data. Do not compute differences or percentages, do not judge how close two
numbers are, and do not score 0 because a figure looks too high or too low.
Judge the chart's structure and coverage: does it plot the right measure, for
the right place and period, broken down the way the query needs? A chart that is
structurally right is a 1 even if you suspect its numbers.

"""
        + codeact_instruction
        + """Return:
- score: 1 or 0
- reason: one concise sentence explaining why you gave that score"""
    )

    if _using_openrouter_decisions():
        score, reason = _openrouter_binary_judgement(
            check="charts_answer",
            instructions=(
                "Decide whether the provided chart specification(s) are "
                "structurally appropriate for answering the user query and "
                "expected answer. Ignore numeric closeness."
            ),
            state={
                "query": query,
                "expected_answer": expected_answer,
                "charts_json": charts_json,
                "codeact_summary": codeact_summary,
            },
        )
        llm_judgement = ChartScore(score=score, reason=reason)
    else:
        JUDGE_PROMPT = ChatPromptTemplate.from_messages(
            [
                (
                    "user",
                    full_prompt,
                ),
            ],
        )

        judge_chain = JUDGE_PROMPT | HAIKU.with_structured_output(ChartScore)

        invoke_kwargs = {
            "query": query,
            "expected_answer": expected_answer,
            "charts_json": charts_json,
        }
        if codeact_summary:
            invoke_kwargs["codeact_summary"] = codeact_summary

        llm_judgement = judge_chain.invoke(invoke_kwargs)

    numeric = evaluate_numeric_support(expected_answer, charts_json, NUMERIC_TOLERANCE)
    verdict = resolve_chart_verdict(
        judge_score=llm_judgement.score,
        judge_reason=llm_judgement.reason,
        support=numeric["support"],
        explanation=numeric["explanation"],
    )

    if include_reason:
        return verdict

    return verdict["score"]


def llm_judge_expected_text(
    expected_text: str,
    actual_answer: str,
    include_reason: bool = False,
) -> int | dict[str, int | str]:
    """Judge whether an answer includes semantically similar expected text."""

    class TextMatchScore(BaseModel):
        reason: str
        score: int

    if _using_openrouter_decisions():
        score, reason = _openrouter_binary_judgement(
            check="expected_text_match",
            instructions=(
                "Decide whether the ACTUAL_AGENT_RESPONSE includes the "
                "EXPECTED_TEXT_OR_INSTRUCTION semantically, allowing paraphrase."
            ),
            state={
                "expected_text_or_instruction": expected_text,
                "actual_agent_response": actual_answer,
            },
        )
        judgement = TextMatchScore(score=score, reason=reason)
    else:
        JUDGE_PROMPT = ChatPromptTemplate.from_messages(
            [
                (
                    "user",
                    """
                    You are evaluating whether an AI-generated response includes
                    the expected information, meaning, or behavior.

                    EXPECTED TEXT OR INSTRUCTION:
                    {expected_text}

                    ACTUAL AGENT RESPONSE:
                    {actual_answer}

                    Return score 1 if the actual response includes information that
                    is semantically similar to the expected text, even if the wording
                    is different. Also return 1 if the expected text is an
                    instruction or qualitative behavior and the response satisfies
                    it.

                    Return score 0 if the response omits, contradicts, or only
                    weakly implies the expected text or behavior.

                    Examples:
                    - Expected "30 x 30 resolution" matches responses that say
                      "30-meter by 30-meter pixels" or "30 m resolution".
                    - Expected "clarifies to user that dataset isn't available"
                      matches responses that explain the requested dataset is not
                      available and ask the user to choose another option.

                    Return:
                    - score: 1 if the expected text/behavior is included, otherwise 0
                    - reason: one concise sentence explaining why you gave that score
                    """,
                ),
            ],
        )

        judge_chain = JUDGE_PROMPT | HAIKU.with_structured_output(TextMatchScore)
        judgement = judge_chain.invoke(
            {
                "expected_text": expected_text,
                "actual_answer": actual_answer,
            },
        )

    if include_reason:
        return {
            "score": judgement.score,
            "reason": judgement.reason,
        }

    return judgement.score
