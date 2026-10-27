"""Deterministic numeric check for chart rows.

Decides whether a chart's own data contains the figure in the case's expected
answer. The LLM chart judge is never asked to compare numbers, because its
arithmetic is unreliable: asked about a chart whose yearly values sum to 25.31 Mha,
it reported the same chart as summing to 27.4 Mha and to 26.0 Mha. Its view on
whether the chart suits the query is recorded as the info-only
`charts_answer_judge`.

Candidate figures come from the chart data: leaf values, column totals and maxima,
cross-column row sums and, when the expected figure is a percentage, each value's
share of its column total.

Support is three-valued: "supported", "unsupported", or `None` when there is no
numeric claim to check (a year, a place name, or a figure whose decimal separator
is ambiguous). `None` leaves `charts_answer` unscored; see `resolve_chart_verdict`
in `llm_judges.py`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

# Scale written as a word, which expected answers use as often as a unit prefix:
# "25.54 million hectares" sits beside "25 Mha".
_SCALE_WORDS = {
    "thousand": 1_000,
    "million": 1_000_000,
    "billion": 1_000_000_000,
}

# Unit suffix -> multiplier into the unit the chart data is encoded in. Anything not
# listed is treated as a bare number (MgCO2e, tonnes, counts), which compares directly.
_UNIT_MULTIPLIERS = {
    "mha": 1_000_000,
    "kha": 1_000,
    "ha": 1,
    "hectares": 1,
    "hectare": 1,
    "hektar": 1,  # Indonesian; gold has multilingual rows
    "hektare": 1,
}

# Keys that hold labels or ordinals rather than measures. Summing a `year` column gives
# 50,325, which would otherwise become a candidate figure.
_NON_MEASURE_KEYS = frozenset(
    {
        "year",
        "years",
        "month",
        "day",
        "date",
        "id",
        "index",
        "order",
        "position",
        "rank",
    },
)

# A number written as `230.003` may be two hundred thousand (Indonesian, Spanish) or two
# hundred point oh oh three. Exactly three digits after a single dot, with no second
# decimal group, is unresolvable from the string alone.
_AMBIGUOUS_DECIMAL = re.compile(r"^\d{1,3}\.\d{3}$")

# A leading number, optionally signed, with thousands separators and a decimal
# part. The sign matters: net-flux answers express a carbon sink as a negative
# ("-286,994 Mg CO2e"), and dropping it turns an exact match into a large miss.
#
# The lookbehind stops a word-internal hyphen reading as a minus: in "Sentinel-2"
# the 2 is positive. A hyphen after a letter or digit is a separator, never a sign.
_NUMBER = re.compile(r"(?<![A-Za-z0-9])(-?\d[\d,]*(?:\.\d+)?)")

_YEAR = re.compile(r"^(19|20)\d{2}$")


def format_number(value: float) -> str:
    """Render a figure the way expected answers write it, not as 2.5e+07.

    These strings appear in check reasons beside the case's expected answer, so
    thousands separators matter more than compactness. Shared by the chart
    comparator and the answer judge's numeric override (`llm_judges.py`).
    """
    if abs(value) >= 1_000:
        return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"
    return f"{value:g}"


@dataclass(frozen=True)
class ExpectedNumber:
    """A numeric claim parsed from answer text, usually a case's expected answer."""

    value: float
    is_percent: bool
    raw: str


def parse_expected_number(expected_answer: str) -> ExpectedNumber | None:
    """Pull the figure out of an expected answer, or None when there isn't one to check.

    Returns None for years ("2003"), bare named entities ("Waikato"), empty text, and
    figures whose decimal separator is ambiguous: every input where a deterministic
    comparison would be a guess.
    """
    text = (expected_answer or "").strip()
    if not text:
        return None

    match = _NUMBER.search(text)
    if not match:
        return None

    # Trailing separators are punctuation, not part of the number: in "In 2020,
    # 25.5 Mha" the token "2020," would otherwise miss the year guard and become
    # the expected value.
    token = match.group(1).rstrip(",.")
    if not token or token == "-":
        return None
    # The year and ambiguous-separator guards describe the digits, so they are
    # tested against the magnitude: a sign must not smuggle a value past them.
    magnitude = token.lstrip("-")
    if _YEAR.match(magnitude):
        return None
    if _AMBIGUOUS_DECIMAL.match(magnitude):
        return None

    try:
        value = float(token.replace(",", ""))
    except ValueError:
        return None
    if value == 0:
        # A relative difference against zero is undefined.
        return None

    remainder = text[match.end() :].lstrip()
    is_percent = remainder.startswith("%")
    if not is_percent:
        # A written scale comes before the unit: "million hectares", "billion tCO2e".
        word = re.match(r"[A-Za-z]+", remainder)
        if word and word.group(0).lower() in _SCALE_WORDS:
            value *= _SCALE_WORDS[word.group(0).lower()]
            remainder = remainder[word.end() :].lstrip()

        unit = re.match(r"[A-Za-z²]+", remainder)
        if unit:
            value *= _UNIT_MULTIPLIERS.get(unit.group(0).lower(), 1)

    return ExpectedNumber(value=value, is_percent=is_percent, raw=token)


def _numeric_items(node: Any) -> list[tuple[str, float]]:
    """Every numeric leaf in the structure, paired with the key that held it."""
    found: list[tuple[str, float]] = []

    def walk(value: Any, key: str) -> None:
        if isinstance(value, bool):
            return
        if isinstance(value, int | float):
            found.append((key.lower(), float(value)))
        elif isinstance(value, dict):
            for k, v in value.items():
                walk(v, str(k))
        elif isinstance(value, list):
            for item in value:
                walk(item, key)

    walk(node, "")
    return found


def _series_aggregates(node: Any) -> list[float]:
    """Totals and maxima of every measure column in every list-of-records found.

    A chart that plots 25 yearly values supports an expected period total even though it
    never draws one, so the sum has to be a candidate.
    """
    aggregates: list[float] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
            return
        if not isinstance(value, list):
            return

        records = [item for item in value if isinstance(item, dict)]
        if records:
            keys = {k for record in records for k in record}
            for key in keys:
                if key.lower() in _NON_MEASURE_KEYS:
                    continue
                numbers = [
                    float(record[key])
                    for record in records
                    if isinstance(record.get(key), int | float)
                    and not isinstance(record.get(key), bool)
                ]
                if numbers:
                    aggregates.append(sum(numbers))
                    aggregates.append(max(numbers))
        for item in value:
            walk(item)

    walk(node)
    return aggregates


def _cross_column_totals(node: Any) -> list[float]:
    """Per-record sums across measure columns, plus their grand total.

    A chart that splits one quantity across several measure columns (for example
    alerts as `high_confidence` and `highest_confidence`) never draws the combined
    figure, but a reader takes it straight off the chart.

    Only record sets with at least two measure columns contribute, so
    single-series charts gain nothing. A wider candidate set makes the check more
    permissive; that trade is deliberate, and label columns never enter a sum
    (a year plus an area is not a figure anyone reads).
    """
    totals: list[float] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
            return
        if not isinstance(value, list):
            return

        records = [item for item in value if isinstance(item, dict)]
        if records:
            measure_keys = sorted(
                {
                    key
                    for record in records
                    for key in record
                    if key.lower() not in _NON_MEASURE_KEYS
                },
            )
            if len(measure_keys) >= 2:
                row_sums: list[float] = []
                for record in records:
                    numbers = [
                        float(record[key])
                        for key in measure_keys
                        if isinstance(record.get(key), int | float)
                        and not isinstance(record.get(key), bool)
                    ]
                    if len(numbers) >= 2:
                        row_sums.append(sum(numbers))
                totals.extend(row_sums)
                if row_sums:
                    totals.append(sum(row_sums))
        for item in value:
            walk(item)

    walk(node)
    return totals


def _percent_candidates(node: Any) -> list[float]:
    """Each measure value as a percentage of its own column total.

    Charts encode areas, but expected answers often give a share ("8.57%"), so the
    share is derived here rather than asked of the model.
    """
    shares: list[float] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
            return
        if not isinstance(value, list):
            return

        records = [item for item in value if isinstance(item, dict)]
        if records:
            keys = {k for record in records for k in record}
            for key in keys:
                if key.lower() in _NON_MEASURE_KEYS:
                    continue
                numbers = [
                    float(record[key])
                    for record in records
                    if isinstance(record.get(key), int | float)
                    and not isinstance(record.get(key), bool)
                ]
                total = sum(numbers)
                if total:
                    shares.extend(number / total * 100 for number in numbers)
        for item in value:
            walk(item)

    walk(node)
    return shares


def chart_candidate_values(charts_json: str, is_percent: bool = False) -> list[float]:
    """Every figure a reader could take from the chart, for matching against expected.

    Leaf values, column totals and column maxima; cross-column row sums and their grand
    total; plus per-column shares when the expected answer is a percentage.
    Label-ish columns (`year`, `id`, ...) are excluded from every aggregate so their sums
    don't become candidates.
    """
    try:
        charts = json.loads(charts_json or "")
    except (json.JSONDecodeError, TypeError):
        return []

    candidates = [
        value for key, value in _numeric_items(charts) if key not in _NON_MEASURE_KEYS
    ]
    candidates += _series_aggregates(charts)
    candidates += _cross_column_totals(charts)
    if is_percent:
        candidates += _percent_candidates(charts)
    return [value for value in candidates if value != 0]


def evaluate_numeric_support(
    expected_answer: str,
    charts_json: str,
    tolerance: float,
) -> dict[str, Any]:
    """Check whether the chart's own data supports the expected figure.

    Returns `support` as "supported", "unsupported", or None when there is no numeric
    claim to check. `explanation` is written for the score reason so a verdict can be
    audited without re-running anything.
    """
    result: dict[str, Any] = {
        "support": None,
        "expected_value": None,
        "closest_value": None,
        "difference": None,
        "explanation": "",
    }

    expected = parse_expected_number(expected_answer)
    if expected is None:
        return result

    result["expected_value"] = expected.value
    candidates = chart_candidate_values(charts_json, is_percent=expected.is_percent)
    unit = "%" if expected.is_percent else ""

    if not candidates:
        result["support"] = "unsupported"
        result["explanation"] = (
            f"deterministic check: the chart data holds no figure to compare against the "
            f"expected {format_number(expected.value)}{unit}"
        )
        return result

    closest = min(candidates, key=lambda value: abs(value - expected.value))
    difference = abs(closest - expected.value) / abs(expected.value)
    within = difference <= tolerance

    result["support"] = "supported" if within else "unsupported"
    result["closest_value"] = closest
    result["difference"] = difference
    result["explanation"] = (
        f"deterministic check: the chart's closest figure to the expected "
        f"{format_number(expected.value)}{unit} is {format_number(closest)}{unit}, "
        f"a {difference:.2%} difference, "
        f"{'within' if within else 'exceeding'} the {tolerance:.0%} tolerance"
    )
    return result
