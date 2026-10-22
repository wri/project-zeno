"""The ``expected.ground_truth`` selector: which figure out of the response.

    AGG(column)
    AGG(column) WHERE column=value

``AGG`` is ``sum`` / ``max`` / ``min`` / ``count``. An explicit aggregate is
**mandatory** — a bare column reference would be ambiguous whenever the filter
matches more than one row, which is live: 1-038 pulls 2 AOIs and 1-059 pulls 254,
so ``area_ha WHERE year=2019`` would silently reduce 254 rows by an implicit
rule nobody wrote down.

``count`` counts the column's **numeric values**, not the rows the filter
matched: a row whose value is null or non-numeric is skipped, as it is under
every other aggregate. A column with no numeric values at all raises rather
than counting zero, so ``count`` on a categorical column is not a row count.

Parsed and applied in code, never by a judge — ``docs/specs/PLAN.md`` §6:
numbers in code, structure and semantics to the judge.

The selector names the **API's** column, not the agent's. The agent renames
columns in its pandas codeact (1-076's chart says ``loss_area_ha`` where the API
says ``area_ha``), so authoring from an artifact's ``charts_data`` is a trap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

AGGREGATES = {
    "sum": lambda values: sum(values),
    "max": lambda values: max(values),
    "min": lambda values: min(values),
    "count": lambda values: float(len(values)),
}

# The regex accepts `where` in any capitalisation, and `Selector.canonical()`
# prints a parsed selector back in one standard spelling for the run record.
# Neither of those affects a case's uid, which hashes the YAML text exactly as
# typed: a case written `where` and a case written `WHERE` are two different
# uids, so GOLD reads them as two versions of the same test. Authors spell it
# the standard way (`cases/README.md`), and `tools/audit_cases.py` fails
# `--strict` when they do not.
_SELECTOR = re.compile(
    r"^\s*(?P<agg>\w+)\s*\(\s*(?P<column>[\w.]+)\s*\)"
    r"(?:\s+where\s+(?P<key>[\w.]+)\s*=\s*(?P<value>.+?))?\s*$",
    re.IGNORECASE,
)


class SelectorError(Exception):
    """The selector is malformed, or does not resolve against a response."""


@dataclass(frozen=True)
class Selector:
    aggregate: str
    column: str
    filter_column: str | None = None
    filter_value: str | None = None

    def canonical(self) -> str:
        text = f"{self.aggregate}({self.column})"
        if self.filter_column is not None:
            text += f" WHERE {self.filter_column}={self.filter_value}"
        return text


def parse_selector(raw: str) -> Selector:
    match = _SELECTOR.match(raw or "")
    if not match:
        raise SelectorError(
            f"cannot parse ground_truth {raw!r}; expected "
            "'AGG(column)' or 'AGG(column) WHERE column=value'"
        )
    aggregate = match.group("agg").lower()
    if aggregate not in AGGREGATES:
        raise SelectorError(
            f"unknown aggregate {aggregate!r}; expected one of {sorted(AGGREGATES)}"
        )
    value = match.group("value")
    if value is not None:
        value = value.strip().strip("'\"")
    return Selector(aggregate, match.group("column"), match.group("key"), value)


def _split_columns(
    result: dict[str, Any],
) -> tuple[dict[str, list[Any]], dict[str, Any]]:
    """Separate real columns (lists of values) from ones the API left uncomputed.

    The API returns a bare ``null`` in place of a column it did not compute for
    the request, for example ``carbon_emissions_MgCO2e`` at a low
    ``canopy_cover`` threshold. That is a valid answer, not a malformed
    response, so the remaining columns stay readable.
    """
    columns = {k: v for k, v in result.items() if isinstance(v, list)}
    uncomputed = {k: v for k, v in result.items() if not isinstance(v, list)}
    return columns, uncomputed


def _rows(columns: dict[str, list[Any]]) -> list[dict[str, Any]]:
    """The analytics API answers column-oriented; rows are easier to filter."""
    if not columns:
        return []
    return [dict(zip(columns, values)) for values in zip(*columns.values())]


def _require(column: str, role: str, columns: dict, uncomputed: dict) -> None:
    """A SelectorError for any column the selector needs but cannot read.

    Always a SelectorError, never a TypeError: prefetch turns SelectorError
    into a row error with this message, and anything else escapes as a
    traceback that aborts the run.
    """
    if column in uncomputed:
        raise SelectorError(
            f"{role} {column!r} came back as {uncomputed[column]!r}, not a list of "
            "values: the API did not compute it for this request"
        )
    if column not in columns:
        raise SelectorError(
            f"{role} {column!r} not in the response (columns: {sorted(columns)})"
        )


def apply_selector(selector: Selector, result: dict[str, list[Any]]) -> float:
    """Resolve a selector against one analytics response.

    Raises ``SelectorError`` when the response lacks the column or the filter
    matches nothing. A case whose metric is absent must **error**, never pass
    vacuously — an empty match summing to 0.0 would silently become a
    real-looking expected value.

    A column the API returned as ``null`` is ignored unless the selector needs
    it, in which case it is the same kind of absence and raises the same way.
    """
    columns, uncomputed = _split_columns(result or {})
    _require(selector.column, "column", columns, uncomputed)
    if selector.filter_column is not None:
        _require(selector.filter_column, "filter column", columns, uncomputed)
    rows = _rows(columns)

    if selector.filter_column is not None:
        wanted = selector.filter_value
        rows = [row for row in rows if str(row.get(selector.filter_column)) == wanted]
        if not rows:
            raise SelectorError(
                f"no rows where {selector.filter_column}={wanted!r}; "
                "the metric this case needs is absent from the fetched data"
            )

    values = [
        float(row[selector.column])
        for row in rows
        if isinstance(row.get(selector.column), (int, float))
        and not isinstance(row.get(selector.column), bool)
    ]
    if not values:
        raise SelectorError(
            f"no numeric values in column {selector.column!r} after filtering"
        )
    return float(AGGREGATES[selector.aggregate](values))
