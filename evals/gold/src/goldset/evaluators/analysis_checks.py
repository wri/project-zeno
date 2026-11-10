"""Analysis-bucket checks, both deterministic (numbers are compared in code,
never by a judge).

``class_value_match`` compares per-class figures (for example
"mangroves=15,444 hectares") with the chart and statistics data. It catches a
wrong sub-total under a correct headline total, which ``agent_answer`` only sees
if the error moves the total past the tolerance. Currently info-only
(``buckets.INFO_ONLY``).

``chart_integrity`` fails a chart whose axis fields are null in any record.
Nulls there usually mean two record sets were merged into one array (for
example a ranking and a breakdown), and the prose then quotes the wrong figure.
"""

from __future__ import annotations

from typing import Any

from goldset.evaluators.chart_numeric import parse_expected_number
from goldset.evaluators.llm_judges import NUMERIC_TOLERANCE


def _data_records(agent_state: dict[str, Any]) -> list[dict[str, Any]]:
    """Every record dict from chart data arrays and the last statistics pull."""
    records: list[dict[str, Any]] = []
    for chart in agent_state.get("charts_data") or []:
        if not isinstance(chart, dict):
            continue
        data = chart.get("data")
        if isinstance(data, list):
            records += [row for row in data if isinstance(row, dict)]
    statistics = agent_state.get("statistics")
    if isinstance(statistics, list):
        statistics = statistics[-1] if statistics else None
    if isinstance(statistics, dict):
        data = statistics.get("data")
        if isinstance(data, list):
            records += [row for row in data if isinstance(row, dict)]
    return records


def _numeric_values(record: dict[str, Any]) -> list[float]:
    return [
        float(value)
        for value in record.values()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]


def parse_class_values(expected: str) -> list[tuple[str, str]] | None:
    """``"mangroves=15,444 hectares; other=3 ha"`` -> [(name, value_text)].
    None when any pair is malformed: abstain rather than half-check."""
    pairs = []
    for chunk in expected.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            return None
        name, _, value_text = chunk.partition("=")
        if not name.strip() or not value_text.strip():
            return None
        pairs.append((name.strip(), value_text.strip()))
    return pairs or None


def evaluate_class_values(
    agent_state: dict[str, Any], expected_class_values: str
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "class_value_match_score": None,
        "actual_class_values": None,
    }
    if not expected_class_values:
        return result

    pairs = parse_class_values(expected_class_values)
    if pairs is None:
        result["actual_class_values"] = (
            f"malformed expected_class_values {expected_class_values!r}; abstained"
        )
        return result

    records = _data_records(agent_state)
    if not records:
        result["class_value_match_score"] = 0.0
        result["actual_class_values"] = "no data records to check classes against"
        return result

    findings = []
    all_ok = True
    for name, value_text in pairs:
        target = parse_expected_number(value_text)
        if target is None:
            result["actual_class_values"] = (
                f"unparseable value {value_text!r} for class {name!r}; abstained"
            )
            return {**result, "class_value_match_score": None}
        matching = [
            record
            for record in records
            if any(
                isinstance(value, str) and name.lower() in value.lower()
                for value in record.values()
            )
        ]
        candidates = [v for record in matching for v in _numeric_values(record)]
        if not candidates:
            findings.append(f"{name}: no matching record")
            all_ok = False
            continue
        closest = min(candidates, key=lambda v: abs(v - target.value))
        difference = abs(closest - target.value) / abs(target.value)
        ok = difference <= NUMERIC_TOLERANCE
        all_ok = all_ok and ok
        findings.append(f"{name}: closest {closest:,.2f} ({difference:.2%})")

    result["class_value_match_score"] = 1.0 if all_ok else 0.0
    result["actual_class_values"] = "; ".join(findings)
    return result


def evaluate_chart_integrity(agent_state: dict[str, Any]) -> dict[str, Any]:
    """Axis-referenced fields must be non-null in every record. Expectation-
    free: runs on any row that produced charts."""
    charts = agent_state.get("charts_data") or []
    result: dict[str, Any] = {
        "chart_integrity_score": None,
        "chart_integrity_reason": None,
    }
    if not charts:
        return result

    problems = []
    for index, chart in enumerate(charts):
        if not isinstance(chart, dict):
            continue
        data = chart.get("data")
        if not isinstance(data, list):
            continue
        records = [row for row in data if isinstance(row, dict)]
        for axis in ("xAxis", "yAxis"):
            field = chart.get(axis)
            if not isinstance(field, str) or not field:
                continue
            padded = sum(
                1 for record in records if field in record and record[field] is None
            )
            if padded:
                problems.append(
                    f"chart {index} ({chart.get('type', '?')}): {axis} field "
                    f"{field!r} is null in {padded}/{len(records)} records — "
                    "mis-joined record sets"
                )
    result["chart_integrity_score"] = 0.0 if problems else 1.0
    if problems:
        result["chart_integrity_reason"] = "; ".join(problems)
    return result
