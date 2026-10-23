"""Data pull evaluator.

Two independent date checks live here, measuring different things:

- ``evaluate_date_extraction`` reads the ``start_date``/``end_date`` **arguments the
  agent passed to its own tools** (``pull_data``, falling back to ``pick_dataset``).
  That is the agent's interpretation of the period named in the prompt, and it has
  been consistent across trials and languages.
- ``evaluate_date_selection`` compares the *recorded* range in agent state against
  the request, asking only whether the data pulled **covers** the requested period.

The distinction matters because ``agent_state["start_date"]`` is unreliable: for the
same query it has recorded the requested window, the dataset's full coverage extent
(for example 2001 to 2025 for tree cover loss), and a rolling window ending today.
Only the tool arguments consistently reflect what the agent was actually asked to
look for, which is why extraction is the scored check and coverage is reported for
diagnosis.
"""

from typing import Any

from goldset.evaluators.utils import (
    last_statistics,
    normalize_end_date,
    normalize_start_date,
)

# Tools whose arguments carry the agent's chosen analysis window, most authoritative
# first. `pull_data` is the actual request; `pick_dataset` is an earlier echo of it.
_DATE_BEARING_TOOLS = ("pull_data", "pick_dataset")


def _tool_call_date_windows(
    agent_state: dict[str, Any],
) -> list[tuple[str, str, str]]:
    """Collect ``(tool_name, start_date, end_date)`` from every dated tool call.

    Walks ``agent_state["messages"]`` for ``tool_calls`` the same way
    ``APITestRunner._format_tool_trace`` does. Messages are LangChain objects, so
    ``tool_calls`` is read defensively via ``getattr``.
    """
    windows: list[tuple[str, str, str]] = []
    for message in agent_state.get("messages") or []:
        for tool_call in getattr(message, "tool_calls", None) or []:
            if not isinstance(tool_call, dict):
                continue
            args = tool_call.get("args")
            if not isinstance(args, dict):
                continue
            start = str(args.get("start_date") or "").strip()
            end = str(args.get("end_date") or "").strip()
            if start or end:
                windows.append((str(tool_call.get("name") or ""), start, end))
    return windows


def _preferred_windows(
    windows: list[tuple[str, str, str]],
) -> list[tuple[str, str, str]]:
    """Narrow to the most authoritative tool that supplied dates."""
    for tool_name in _DATE_BEARING_TOOLS:
        matching = [w for w in windows if w[0] == tool_name]
        if matching:
            return matching
    return windows


def evaluate_date_extraction(
    agent_state: dict[str, Any],
    expected_start_date: str | None = None,
    expected_end_date: str | None = None,
) -> dict[str, Any]:
    """Check the agent extracted the requested period from the prompt.

    Scored against the ``start_date``/``end_date`` arguments the agent passed to
    ``pull_data`` (or ``pick_dataset``), not against recorded state. A row may make
    more than one dated call; the check passes if **any** of them matches, so a
    comparative query that pulls twice is not penalised.

    Args:
        agent_state: Final agent state after execution
        expected_start_date: Expected start date in any supported format
        expected_end_date: Expected end date in any supported format

    Returns:
        Dict with:
        - date_extraction_score (0/1/None): 1.0 if a dated tool call matches both
          expected dates, 0.0 if none does, None if no expected dates were given or
          the expected dates are unparseable
        - actual_extracted_start_date / actual_extracted_end_date (str | None): the
          matching window, or the last observed one when nothing matched
        - date_extraction_source (str | None): tool that supplied the window
        - actual_extracted_windows (str | None): every observed window, for diagnosis

    """
    windows = _preferred_windows(_tool_call_date_windows(agent_state))
    all_windows = (
        "; ".join(f"{name}:{start}..{end}" for name, start, end in windows) or None
    )
    result: dict[str, Any] = {
        "date_extraction_score": None,
        "actual_extracted_start_date": None,
        "actual_extracted_end_date": None,
        "date_extraction_source": windows[-1][0] if windows else None,
        "actual_extracted_windows": all_windows,
    }

    if windows:
        result["actual_extracted_start_date"] = windows[-1][1] or None
        result["actual_extracted_end_date"] = windows[-1][2] or None

    # No expectation, or an expectation the harness cannot parse -> not evaluated.
    if not expected_start_date or not expected_end_date:
        return result
    expected_start = normalize_start_date(expected_start_date)
    expected_end = normalize_end_date(expected_end_date)
    if not expected_start or not expected_end:
        return result

    # Dates were expected but the agent never scoped a request: it did not look for
    # a period at all, which is a failure rather than an absent check.
    if not windows:
        result["date_extraction_score"] = 0.0
        return result

    for name, start, end in windows:
        # An omitted bound is an open-ended request ("from 2001 onwards"), which the
        # agent does use, e.g. pull_data(start_date="2001-01-01") with no end. Only
        # the bounds the agent actually supplied are checked; the other side is
        # unconstrained and left to date_coverage. Requiring both would fail a
        # legitimately open-ended pull.
        start_ok = (
            normalize_start_date(start) == expected_start if start.strip() else True
        )
        end_ok = normalize_end_date(end) == expected_end if end.strip() else True
        if start_ok and end_ok:
            result.update(
                {
                    "date_extraction_score": 1.0,
                    "actual_extracted_start_date": start or None,
                    "actual_extracted_end_date": end or None,
                    "date_extraction_source": name,
                },
            )
            return result

    result["date_extraction_score"] = 0.0
    return result


def _latest_statistics(agent_state: dict[str, Any]) -> dict[str, Any]:
    """The most recent statistics entry, or {} — callers here index it freely."""
    return last_statistics(agent_state) or {}


def _count_rows(raw_data: Any) -> int:
    """Count rows in legacy inline statistics data."""
    if isinstance(raw_data, list):
        return len(raw_data)
    if isinstance(raw_data, dict):
        if not raw_data:
            return 0
        lengths = [len(v) for v in raw_data.values() if isinstance(v, list)]
        return max(lengths) if lengths else 0
    return 0


def _data_pull_outcome(
    stat_entry: dict[str, Any],
    *,
    min_rows: int,
) -> tuple[bool, int, str]:
    """Determine whether a data pull succeeded and how many rows are available."""
    source_url = (stat_entry.get("source_url") or "").strip()
    pull_id = (stat_entry.get("id") or "").strip()
    if source_url or pull_id:
        return True, 1, ""

    row_count = _count_rows(stat_entry.get("data"))
    if row_count < min_rows:
        return False, row_count, "insufficient rows of data retrieved"
    return True, row_count, ""


def evaluate_date_selection(
    agent_state: dict[str, Any],
    expected_start_date: str | None = None,
    expected_end_date: str | None = None,
) -> dict[str, Any]:
    """Check the recorded date range **covers** the requested period.

    Containment, not equality: the agent legitimately pulls a wider range than asked
    for and slices in code, so demanding an exact match penalises correct behaviour.
    This asks the only question the recorded range can answer: was the requested
    period inside the data that was pulled.

    Reported for diagnosis only (``date_coverage`` is in ``buckets.INFO_ONLY``, so it
    never affects a verdict), because ``agent_state["start_date"]`` is inconsistent
    about what it records (see the module docstring). ``evaluate_date_extraction``
    is the scored date check.

    Args:
        agent_state: Final agent state after execution
        expected_start_date: Expected start date in various formats (M/D/YYYY, YYYY-MM-DD, etc.)
        expected_end_date: Expected end date in various formats

    Returns:
        Dict with:
        - date_coverage_score (0/1/None): 1.0 if the recorded range contains the
          expected range, 0.0 if it misses any of it or no range was recorded,
          None if no expected dates provided or expected dates are invalid
        - date_success (bool | None): Boolean version of date_coverage_score
        - actual_start_date (str | None): Actual start date from agent state
        - actual_end_date (str | None): Actual end date from agent state

    """
    stat_entry = _latest_statistics(agent_state)
    actual_start_date = agent_state.get("start_date") or stat_entry.get(
        "start_date",
        "",
    )
    actual_end_date = agent_state.get("end_date") or stat_entry.get("end_date", "")

    if not expected_start_date or not expected_end_date:
        return {
            "date_coverage_score": None,
            "date_success": None,
            "actual_start_date": actual_start_date or None,
            "actual_end_date": actual_end_date or None,
        }

    expected_start_str = normalize_start_date(expected_start_date)
    expected_end_str = normalize_end_date(expected_end_date)

    if not expected_start_str or not expected_end_str:
        return {
            "date_coverage_score": None,
            "date_success": None,
            "actual_start_date": actual_start_date or None,
            "actual_end_date": actual_end_date or None,
        }

    if not actual_start_date or not actual_end_date:
        return {
            "date_coverage_score": 0.0,  # Missing actual = wrong
            "date_success": False,
            "actual_start_date": None,
            "actual_end_date": None,
        }

    actual_start_str = normalize_start_date(actual_start_date)
    actual_end_str = normalize_end_date(actual_end_date)

    if not actual_start_str or not actual_end_str:
        return {
            "date_coverage_score": 0.0,  # Invalid actual = wrong
            "date_success": False,
            "actual_start_date": actual_start_date,
            "actual_end_date": actual_end_date,
        }

    # Containment: the recorded range must contain the requested range.
    date_success = (
        actual_start_str <= expected_start_str and actual_end_str >= expected_end_str
    )
    date_coverage_score = 1.0 if date_success else 0.0

    return {
        "date_coverage_score": date_coverage_score,
        "date_success": date_success,
        "actual_start_date": actual_start_date,
        "actual_end_date": actual_end_date,
    }


def evaluate_data_pull(
    agent_state: dict[str, Any],
    *,
    expects_data_pull: bool,
    min_rows: int = 1,
    query: str = "",
) -> dict[str, Any]:
    """Check if data was successfully pulled.

    Clarification detection is handled separately by evaluate_clarification().
    Dates are checked separately by evaluate_date_extraction() (scored) and
    evaluate_date_selection() (info-only).

    Args:
        agent_state: Final agent state after execution
        expects_data_pull: Whether this case requires analytics data (an
            ``expected_answer``, or an expected ``insight`` dashboard widget)
        min_rows: Minimum number of rows expected (legacy inline data only)
        query: Original user query (kept for compatibility but not used)

    Returns:
        Dict with:
        - data_pull_exists_score (0/1/None): 1.0 if data pull succeeded,
          0.0 if pull missing or failed, None if not applicable
        - row_count (int): 1 when the entry has a source_url or id, else the legacy
          inline row count
        - data_pull_success (bool): Whether data pull met success criteria
        - data_pull_error (str): Diagnostic message when evaluated and failed

    """
    if not expects_data_pull:
        return {
            "data_pull_exists_score": None,
            "row_count": 0,
            "data_pull_success": False,
            "data_pull_error": "",
        }

    stat_entry = _latest_statistics(agent_state)
    if stat_entry:
        data_pull_success, row_count, error = _data_pull_outcome(
            stat_entry,
            min_rows=min_rows,
        )
    else:
        data_pull_success = False
        row_count = 0
        error = "no data retrieved"

    data_pull_exists_score = 1.0 if data_pull_success else 0.0

    return {
        "data_pull_exists_score": data_pull_exists_score,
        "row_count": row_count,
        "data_pull_success": data_pull_success,
        "data_pull_error": error,
    }
