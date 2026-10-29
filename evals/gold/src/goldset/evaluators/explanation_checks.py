"""Explanation-bucket check: answer traceability.

The deterministic "does the answer mislead" check: the headline number the
prose asserts must be derivable from the charts shown beside it (leaf, sum,
max, or share, within ``NUMERIC_TOLERANCE``). It needs no expectation: it
compares the agent's own outputs, so it runs on any row with a chart and a
bolded numeric claim. It exists because an answer can quote a headline figure
that appears nowhere in its own chart and still pass ``agent_answer``.
Currently info-only (``buckets.INFO_ONLY``).

Precision over recall: only **bolded** segments are considered claims (the
answer template bolds key findings), and the number parser inherits
chart_numeric's abstention rules (years skipped, ambiguous locale decimals
abstain): a multilingual row that can't be parsed safely is a ``None``,
never a guess.
"""

from __future__ import annotations

import re
from typing import Any

from goldset.evaluators.answer_evaluator import (
    _serialize_charts_json,
    extract_final_answer_text,
)
from goldset.evaluators.chart_numeric import (
    evaluate_numeric_support,
    parse_expected_number,
)
from goldset.evaluators.llm_judges import NUMERIC_TOLERANCE

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)

# A measure carries a unit, scale word, or percent. Bare numbers in bold are
# usually counts or ranks ("**2** datasets", "top **5**"), the main source of
# false positives.
_MEASURE_RE = re.compile(
    r"\d[\d,.]*\s*(?:%|(?:percent|mha|kha|ha|hectares?|hektare?|hektar|km²|km2"
    r"|tonnes?|mgco2e|tco2e|thousand|million|billion)\b)",
    re.IGNORECASE,
)


def first_bold_claim(prose: str) -> str | None:
    """The first bolded segment carrying a parseable number WITH a unit."""
    for segment in _BOLD_RE.findall(prose):
        if _MEASURE_RE.search(segment) and parse_expected_number(segment) is not None:
            return segment.strip()
    return None


def evaluate_answer_traceability(agent_state: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "answer_traceability_score": None,
        "answer_traceability_reason": None,
        "actual_traceability_claim": None,
    }
    charts = agent_state.get("charts_data") or []
    prose = extract_final_answer_text(agent_state.get("messages", []))
    if not charts or not prose:
        return result

    claim = first_bold_claim(prose)
    if claim is None:
        result["answer_traceability_reason"] = "no bolded numeric claim found"
        return result

    support = evaluate_numeric_support(
        claim, _serialize_charts_json(charts), NUMERIC_TOLERANCE
    )
    result["actual_traceability_claim"] = claim
    result["answer_traceability_reason"] = support["explanation"] or None
    if support["support"] == "supported":
        result["answer_traceability_score"] = 1.0
    elif support["support"] == "unsupported":
        result["answer_traceability_score"] = 0.0
    return result
