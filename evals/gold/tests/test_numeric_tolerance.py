"""Unit tests for the answer judge's numeric tolerance.

The judge only extracts the number in the answer that responds to the
question (`extracted_number`). `resolve_answer_verdict` then applies the
tolerance in code, as `resolve_chart_verdict` does for charts. One
difference: a deterministic FAIL falls back to the judge's verdict, because
the parser cannot read some formats the judge can (a French decimal comma in
1-091, a Chinese scale word in 1-094). A deterministic PASS is final.

Without an API call, these tests check that:

- the tolerance is defined once and appears in the prompt;
- the prompt does not ask the model to compute the match;
- the shared prompt fragment adds no LangChain template variables (a stray
  `{` would become a required variable and fail the judge call at runtime);
- the deterministic and judge verdicts combine correctly.
"""

from langchain_core.prompts import ChatPromptTemplate

from goldset.evaluators.llm_judges import (
    _NUMERIC_RULES,
    ANSWER_JUDGE_PROMPT,
    NUMERIC_TOLERANCE,
    resolve_answer_verdict,
)

TOLERANCE_PCT = f"{NUMERIC_TOLERANCE:.0%}"


def test_tolerance_is_two_percent():
    """The agreed threshold. Changing it should be a deliberate, visible edit."""
    assert NUMERIC_TOLERANCE == 0.02


def test_answer_judge_prompt_states_the_tolerance_and_the_extraction_field():
    """The deterministic override decides numeric rows on this figure, so the
    prompt must carry it and must tell the model what to extract."""
    assert f"{TOLERANCE_PCT} tolerance" in ANSWER_JUDGE_PROMPT
    assert "extracted_number" in ANSWER_JUDGE_PROMPT
    assert _NUMERIC_RULES in ANSWER_JUDGE_PROMPT


def test_prompt_does_not_ask_the_model_to_compute_the_match():
    """The prompt must not ask the model to do the arithmetic: the judge is
    inconsistent at it (on 1-009 it accepted a 0.51% difference in one trial
    and rejected the same difference in another)."""
    assert "Tolerance formula" not in _NUMERIC_RULES
    assert "MATCH (1)" not in _NUMERIC_RULES
    assert "NO MATCH (0)" not in _NUMERIC_RULES


def test_numeric_rules_add_no_template_variables():
    """A stray brace in the fragment would become a required input variable."""
    assert (
        ChatPromptTemplate.from_messages([("user", _NUMERIC_RULES)]).input_variables
        == []
    )


def test_assembled_prompt_exposes_exactly_the_expected_variables():
    """Guards against the fragment capturing or dropping a placeholder."""
    answer = ChatPromptTemplate.from_messages([("user", ANSWER_JUDGE_PROMPT)])
    assert sorted(answer.input_variables) == ["actual_answer", "expected_answer"]


# --------------------------------------------------------- resolve_answer_verdict


def test_deterministic_check_overrides_a_wrong_judge_rejection():
    """1-009's actual defect: the judge rejected a delta that is inside tolerance."""
    verdict = resolve_answer_verdict(
        answer_eval_type="numeric",
        expected_answer="3.93%",
        extracted_number="3.95%",
        judge_score=0,
        judge_reason="0.51% exceeds the 2% tolerance",
    )
    assert verdict["score"] == 1
    assert "deterministic check" in verdict["reason"]


def test_a_deterministic_fail_falls_back_to_a_judge_pass():
    """The asymmetric fallback: a deterministic FAIL is not final, because the
    parser is locale-blind in a way the judge (reading the actual prose) is
    not. This is the accepted trade-off (a lenient judge could rescue a
    genuine miss here too), but it's one-directional (see the next test):
    a deterministic PASS is never revisited, so this can only ever turn a
    FAIL into a PASS, never the reverse."""
    verdict = resolve_answer_verdict(
        answer_eval_type="numeric",
        expected_answer="100 hectares",
        extracted_number="110 hectares",
        judge_score=1,
        judge_reason="close enough",
    )
    assert verdict["score"] == 1
    assert "overriding the deterministic check" in verdict["reason"]
    assert "close enough" in verdict["reason"]


def test_a_deterministic_fail_agreeing_with_a_judge_fail_stays_failed():
    verdict = resolve_answer_verdict(
        answer_eval_type="numeric",
        expected_answer="100 hectares",
        extracted_number="110 hectares",
        judge_score=0,
        judge_reason="the figures genuinely differ",
    )
    assert verdict["score"] == 0
    assert "the figures genuinely differ" in verdict["reason"]
    assert "overriding" not in verdict["reason"]


def test_a_deterministic_pass_is_never_revisited_by_the_judge():
    """The override runs in one direction only: a judge FAIL never overturns a
    deterministic PASS. Otherwise the judge's inconsistent arithmetic (seen on
    1-009) would come back as false failures."""
    verdict = resolve_answer_verdict(
        answer_eval_type="numeric",
        expected_answer="100 hectares",
        extracted_number="100 hectares",
        judge_score=0,
        judge_reason="looked wrong to me",
    )
    assert verdict["score"] == 1
    assert "deterministic check" in verdict["reason"]
    assert "looked wrong to me" not in verdict["reason"]


def test_french_decimal_comma_is_rescued_by_the_judge():
    """1-091: the agent correctly answered "289,11 hectares" (French decimal
    comma). The parser reads the comma as a thousands separator and gets
    28,911 (a false ~99x miss), but the judge, reading the actual French
    sentence, correctly recognises it as a match."""
    verdict = resolve_answer_verdict(
        answer_eval_type="numeric",
        expected_answer="289 hectares",
        extracted_number="289,11 hectares",
        judge_score=1,
        judge_reason='"289,11" is French notation for 289.11, matching the expected 289',
    )
    assert verdict["score"] == 1
    assert "overriding the deterministic check" in verdict["reason"]


def test_chinese_scale_word_is_rescued_by_the_judge():
    """1-094: "61.19万公顷" is Chinese for 611,900 hectares (万 = x10,000).
    The parser has no notion of non-English scale words and reads it as bare
    61.19; the judge, reading the actual Chinese text, gets it right."""
    verdict = resolve_answer_verdict(
        answer_eval_type="numeric",
        expected_answer="611,900 hectares",
        extracted_number="61.19万公顷",
        judge_score=1,
        judge_reason="61.19万 is 611,900 in Chinese notation, matching the expected figure",
    )
    assert verdict["score"] == 1
    assert "overriding the deterministic check" in verdict["reason"]


def test_boundary_is_inclusive():
    """100 vs 102 is exactly 2%; the boundary is inclusive."""
    verdict = resolve_answer_verdict(
        answer_eval_type="numeric",
        expected_answer="100 hectares",
        extracted_number="102 hectares",
        judge_score=0,
        judge_reason="looked off",
    )
    assert verdict["score"] == 1


def test_unit_conversion_is_handled_in_code_not_by_the_model():
    """Expected in kha, extracted in hectares: same value, different units."""
    verdict = resolve_answer_verdict(
        answer_eval_type="numeric",
        expected_answer="200 kha",
        extracted_number="200,000 hectares",
        judge_score=0,
        judge_reason="units did not look the same",
    )
    assert verdict["score"] == 1


def test_non_numeric_rows_are_untouched():
    """Boolean, year and named-entity expectations have no figure to compare,
    so the judge's verdict stands."""
    verdict = resolve_answer_verdict(
        answer_eval_type="named_entity",
        expected_answer="Brazil",
        extracted_number="",
        judge_score=1,
        judge_reason="clearly Brazil",
    )
    assert verdict == {"score": 1, "reason": "clearly Brazil"}


def test_falls_back_to_the_judge_when_extraction_is_empty():
    verdict = resolve_answer_verdict(
        answer_eval_type="numeric",
        expected_answer="198.4 hectares",
        extracted_number="",
        judge_score=1,
        judge_reason="best guess",
    )
    assert verdict == {"score": 1, "reason": "best guess"}


def test_falls_back_to_the_judge_when_extraction_does_not_parse():
    """An ambiguous decimal ("230.003") can't be resolved deterministically:
    the same abstention rule the chart comparator uses."""
    verdict = resolve_answer_verdict(
        answer_eval_type="numeric",
        expected_answer="230.003 hectares",
        extracted_number="230.003 hectares",
        judge_score=1,
        judge_reason="looked identical",
    )
    assert verdict == {"score": 1, "reason": "looked identical"}


def test_falls_back_to_the_judge_on_a_percent_unit_mismatch():
    """Expected is a percentage, extracted number is not: a parsing artefact,
    not the population this override is meant to fix."""
    verdict = resolve_answer_verdict(
        answer_eval_type="numeric",
        expected_answer="0.20%",
        extracted_number="5 hectares",
        judge_score=0,
        judge_reason="wrong quantity entirely",
    )
    assert verdict == {"score": 0, "reason": "wrong quantity entirely"}
