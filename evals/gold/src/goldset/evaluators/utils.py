"""Utility functions for evaluators."""

from datetime import datetime


def normalize_gadm_id(gadm_id: str) -> str:
    """Normalise GADM ID for comparison."""
    if not gadm_id:
        return ""
    return gadm_id.split("_")[0].replace("-", ".").lower()


def normalize_value(value) -> str:
    """Normalise values for comparison, handling None, empty strings, and 'None' strings."""
    if value is None or value == "None" or str(value).strip() == "":
        return ""
    return str(value).strip().lower()


def normalize_date(date_str: str | None) -> str:
    """Normalise date strings to YYYY-MM-DD format.

    For YYYY format, defaults to January 1st. For start/end date pairs,
    use normalize_start_date() and normalize_end_date() instead.

    Formats: M/D/YYYY, YYYY-MM-DD, YYYY. Returns empty string if invalid.

    """
    if date_str is None or date_str == "None" or str(date_str).strip() == "":
        return ""

    date_str = str(date_str).strip()

    formats = ["%m/%d/%Y", "%Y-%m-%d", "%Y"]

    for fmt in formats:
        try:
            parsed_date = datetime.strptime(date_str, fmt)
            return parsed_date.strftime("%Y-%m-%d")
        except ValueError:
            continue

    return ""


def normalize_start_date(date_str: str | None) -> str:
    """Normalise a start date to YYYY-MM-DD format.

    YYYY format converts to beginning of year (YYYY-01-01).
    Other formats normalised via normalize_date().

    """
    if not date_str or date_str == "None" or str(date_str).strip() == "":
        return ""

    date_str = str(date_str).strip()

    # YYYY format -> beginning of year
    if len(date_str) == 4 and date_str.isdigit():
        return f"{date_str}-01-01"

    return normalize_date(date_str)


def normalize_end_date(date_str: str | None) -> str:
    """Normalise an end date to YYYY-MM-DD format.

    YYYY format converts to end of year (YYYY-12-31).
    Other formats normalised via normalize_date().

    """
    if not date_str or date_str == "None" or str(date_str).strip() == "":
        return ""

    date_str = str(date_str).strip()

    # YYYY format -> end of year
    if len(date_str) == 4 and date_str.isdigit():
        return f"{date_str}-12-31"

    return normalize_date(date_str)


def last_statistics(agent_state: dict) -> dict | None:
    """The most recent analytics pull recorded in agent state, or None.

    ``statistics`` is normally a list appended to per pull, but a dict has been
    observed, so both are accepted. Shared by the data-pull evaluator, the
    guards, artifact capture and the runner's pulled-data fetch, which each grew
    their own copy of this.
    """
    statistics = agent_state.get("statistics")
    if isinstance(statistics, list):
        statistics = statistics[-1] if statistics else None
    return statistics if isinstance(statistics, dict) else None
