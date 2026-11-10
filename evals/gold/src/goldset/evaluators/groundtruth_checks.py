"""Ground-truth checks: the values fetched at run start against the agent's work."""

from __future__ import annotations

from typing import Any

from goldset.eval_types import ExpectedData
from goldset.evaluators.answer_evaluator import (
    _serialize_charts_json,
    extract_final_answer_text,
)
from goldset.evaluators.chart_numeric import (
    chart_candidate_values,
    format_number,
    parse_expected_number,
)
from goldset.evaluators.llm_judges import NUMERIC_TOLERANCE, judge_answer
from goldset.evaluators.utils import last_statistics
from goldset.groundtruth.selector import SelectorError, apply_selector, parse_selector


def _difference(candidate: float, value: float) -> float:
    """Relative difference; a zero expectation matches only an exact zero."""
    if value == 0:
        return 0.0 if candidate == 0 else float("inf")
    return abs(candidate - value) / abs(value)


def _closest(candidates: list[float], value: float) -> float | None:
    return min(candidates, key=lambda c: _difference(c, value)) if candidates else None


def _pulled_figures(selector_text: str, pulled: dict[str, Any]) -> list[float]:
    """The selector resolved against the agent's table — flat, or per LGMS section."""
    selector = parse_selector(selector_text)
    tables = (
        list(pulled.values())
        if all(isinstance(v, dict) for v in pulled.values())
        else [pulled]
    )
    figures = []
    for table in tables:
        try:
            figures.append(apply_selector(selector, table))
        except SelectorError:
            continue
    return figures


def _match(agent_state: dict[str, Any], expected: ExpectedData) -> dict[str, Any]:
    values = expected.ground_truth_values
    pulled = agent_state.get("pulled_data")
    result: dict[str, Any] = {
        "ground_truth_match_score": None,
        "ground_truth_match_score_reason": None,
        "agent_ground_truth": None,
        # The agent's own figure per expected value, as numbers
        "agent_ground_truth_values": [None] * len(values),
    }

    if isinstance(pulled, dict) and pulled:
        # A readable pull decides alone: a coincidental chart figure must not
        # hide a pull built with the wrong area, dataset, window or parameters.
        figures = _pulled_figures(expected.expected_ground_truth, pulled)
        source = "the agent's pull"
    elif (last_statistics(agent_state) or {}).get("source_url"):
        # The agent pulled but the harness could not read it: the chart is the
        # only evidence left, and without a match we cannot tell whose fault.
        figures = chart_candidate_values(
            _serialize_charts_json(agent_state.get("charts_data") or [])
        )
        source = "the chart (pulled table unreadable)"
    else:
        result["ground_truth_match_score"] = 0.0
        result["ground_truth_match_score_reason"] = "the agent made no data pull"
        return result

    parts, matched = [], True
    for value in values:
        closest = _closest(figures, value)
        within = (
            closest is not None and _difference(closest, value) <= NUMERIC_TOLERANCE
        )
        matched &= within
        found = (
            "nothing"
            if closest is None
            else (f"{format_number(closest)} ({_difference(closest, value):.2%})")
        )
        parts.append(f"expected {format_number(value)}, {source} gives {found}")

    if source == "the agent's pull":
        result["agent_ground_truth_values"] = [_closest(figures, v) for v in values]
    if matched:
        score = 1.0
    elif source.startswith("the chart"):
        score = None
    else:
        score = 0.0
    result["ground_truth_match_score"] = score
    result["ground_truth_match_score_reason"] = (
        f"{expected.expected_ground_truth}: "
        + "; ".join(parts)
        + f" — {'within' if matched else 'exceeding'} the {NUMERIC_TOLERANCE:.0%} tolerance"
    )
    result["agent_ground_truth"] = "; ".join(parts)
    return result


def _answer(agent_state: dict[str, Any], expected: ExpectedData) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ground_truth_answer_score": None,
        "ground_truth_answer_score_reason": None,
        "agent_ground_truth_answer": None,
    }
    prose = extract_final_answer_text(agent_state.get("messages", []))
    if not prose:
        return result

    parts, scores = [], []
    for value in expected.ground_truth_values:
        try:
            extracted = judge_answer(
                f"{format_number(value)} ({expected.expected_ground_truth})", prose
            ).extracted_number
        except Exception as error:
            # Info-only: an outage must not reach judge_errors, which would turn
            # the row into an error and let this check touch a verdict.
            result["ground_truth_answer_score_reason"] = f"JUDGE ERROR: {error}"
            return result
        agent_figure = parse_expected_number(extracted)
        if agent_figure is None or agent_figure.is_percent:
            parts.append(f"no comparable figure extracted ({extracted!r})")
            scores.append(None)
            continue
        difference = _difference(agent_figure.value, value)
        scores.append(1.0 if difference <= NUMERIC_TOLERANCE else 0.0)
        parts.append(
            f"expected {format_number(value)}, prose states {extracted!r} ({difference:.2%})"
        )

    if None not in scores:
        result["ground_truth_answer_score"] = min(scores)
    result["ground_truth_answer_score_reason"] = "; ".join(parts)
    result["agent_ground_truth_answer"] = "; ".join(parts)
    return result


def evaluate_ground_truth(
    agent_state: dict[str, Any], expected: ExpectedData
) -> dict[str, Any]:
    if not expected.expected_ground_truth:
        return {
            "ground_truth_match_score": None,
            "ground_truth_answer_score": None,
        }
    # Both land on TestResult.error through the runner's kwargs merge.
    if expected.ground_truth_unresolved:
        # the fetch worked but this case's metric is absent from the data.
        error = f"ground truth unresolved: {expected.ground_truth_unresolved}"
    elif not expected.ground_truth_values:
        # Never grade against nothing: _match's empty loop would pass vacuously.
        error = "ground truth was not fetched for this case"
    else:
        return {**_match(agent_state, expected), **_answer(agent_state, expected)}
    return {
        "ground_truth_match_score": None,
        "ground_truth_answer_score": None,
        "error": error,
    }
