"""HTTP client for the FAO FRA 2025 public API.

Endpoint used: GET /explorer/data (open-access published data).
Swagger spec: https://fra-data.fao.org/api-docs/swagger.json

This client is used directly by `src.agent.tools.query_fra_data` rather than
through `DataPullOrchestrator` — FAO's response shape and request semantics
(country-level only, fixed reporting years, no parameter sweeps) don't fit the
analytics-API contract that handler exposes.
"""

from typing import Optional

import httpx

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

BASE_URL = "https://fra-data.fao.org/api"
ASSESSMENT_NAME = "fra"
CYCLE_NAME = "2025"
TIMEOUT_SECONDS = 15.0

# FRA reporting years are fixed snapshots — never interpolate between them.
FRA_REPORTING_YEARS = [1990, 2000, 2010, 2015, 2020, 2025]


class FAOAPIError(Exception):
    """FAO API is unreachable or returned a server error."""


class FAODataNotFoundError(Exception):
    """The requested country or variable has no data in FRA 2025."""


def _build_source_url(iso3: str, table: str) -> str:
    return (
        f"{BASE_URL}/explorer/data"
        f"?assessmentName={ASSESSMENT_NAME}"
        f"&countryISOs[]={iso3}"
        f"&tableNames[]={table}"
    )


def _parse_year_key(key: str) -> tuple[int, Optional[str]]:
    """Translate a FAO response time key into (year, period_label).

    The FAO API uses two formats:

    - **Single year** (e.g. `"1990"`, `"2025"`) — snapshot tables like
      `extentOfForest`, `carbonStockTotal`. Returned as `(1990, None)`.
    - **Period** (e.g. `"1990-2000"`, `"2010-2015"`) — rate-of-change
      tables like `forestAreaChange` that report annual rates between
      two reporting cycles. We return `(end_year, "1990-2000")`: the end
      year is the natural x-axis position for a trend chart, and the
      period label is preserved so the analyst can label the bar/point.

    Raises ValueError on anything else so the caller can skip the row.
    """
    parts = key.split("-")
    if len(parts) == 1:
        return int(parts[0]), None
    if len(parts) == 2:
        start, end = int(parts[0]), int(parts[1])
        return end, f"{start}-{end}"
    raise ValueError(f"unrecognised FAO time key: {key!r}")


def _parse_response(
    body: dict,
    iso3: str,
    table: str,
    year: Optional[int],
) -> list[dict]:
    """Flatten the nested FAO response into a list of records.

    Each record: {"year", "period", "variable", "value", "odp", "country"}.
    `period` is None for snapshot-year tables and `"START-END"` for
    rate-of-change tables (see `_parse_year_key`).

    Raises FAODataNotFoundError when the country or table is absent.
    """
    cycle_data = body.get(ASSESSMENT_NAME, {})
    if not cycle_data:
        raise FAODataNotFoundError(f"No FRA data returned for {iso3}.")
    try:
        cycle_key = next(iter(cycle_data))
        country_data = cycle_data[cycle_key].get(iso3)
    except StopIteration as exc:
        raise FAODataNotFoundError(
            f"No FRA data returned for {iso3}."
        ) from exc

    if not country_data:
        raise FAODataNotFoundError(
            f"FRA 2025 does not include data for country '{iso3}'. "
            "Browse available countries at https://fra-data.fao.org."
        )

    table_data = country_data.get(table)
    if not table_data:
        raise FAODataNotFoundError(
            f"FRA 2025 does not include data for table '{table}' for "
            f"{iso3}. Browse available variables at https://fra-data.fao.org."
        )

    records: list[dict] = []
    for time_key, variables in table_data.items():
        try:
            row_year, period = _parse_year_key(time_key)
        except ValueError:
            continue

        if year is not None and row_year != year:
            continue

        for var_name, node in variables.items():
            if not isinstance(node, dict):
                continue
            raw = node.get("raw")
            try:
                value = float(raw) if raw is not None else None
            except (TypeError, ValueError):
                value = None
            records.append(
                {
                    "year": row_year,
                    "period": period,
                    "variable": var_name,
                    "value": value,
                    "odp": bool(node.get("odp", False)),
                    "country": iso3,
                }
            )

    if not records:
        raise FAODataNotFoundError(
            f"FRA 2025 returned no data for table '{table}' for {iso3}."
        )

    return records


async def fetch_fra_data(
    iso3: str,
    table: str,
    variables: list[str],
    year: Optional[int] = None,
) -> list[dict]:
    """Fetch FRA 2025 data for a single country and table.

    Args:
        iso3: Three-letter ISO country code (e.g. "BRA").
        table: FAO FRA table name (e.g. "extentOfForest").
        variables: Variable names to filter on; empty means all variables.
        year: Optional reporting year (must be one of FRA_REPORTING_YEARS).

    Returns:
        List of records, one per (year, variable) pair.

    Raises:
        FAOAPIError: network failure, timeout, or HTTP 5xx.
        FAODataNotFoundError: country or table absent from FRA 2025.
    """
    params: dict = {
        "assessmentName": ASSESSMENT_NAME,
        "countryISOs[]": iso3,
        "tableNames[]": table,
    }
    if variables:
        params["variables[]"] = variables
    if year is not None:
        params["columns[]"] = str(year)

    logger.info(
        f"FAO-CLIENT: GET /explorer/data iso={iso3} table={table} year={year}"
    )

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{BASE_URL}/explorer/data", params=params
            )
    except httpx.TimeoutException as exc:
        raise FAOAPIError(
            "The FAO FRA API did not respond in time. Please try again later."
        ) from exc
    except httpx.RequestError as exc:
        raise FAOAPIError(
            f"Could not reach the FAO FRA API: {exc}. Please try again later."
        ) from exc

    if response.status_code >= 500:
        raise FAOAPIError(
            f"FAO FRA API returned a server error "
            f"({response.status_code}). Please try again later."
        )
    if response.status_code == 401:
        raise FAOAPIError(
            "FAO FRA API requires authentication for this endpoint. "
            "Please contact the GNW team."
        )
    if response.status_code >= 400:
        raise FAODataNotFoundError(
            f"FAO FRA API returned {response.status_code} for "
            f"{iso3} / {table}. The country or variable may not be "
            "available in FRA 2025."
        )

    try:
        body = response.json()
    except Exception as exc:
        raise FAOAPIError(
            "FAO FRA API returned an unexpected response format."
        ) from exc

    return _parse_response(body, iso3, table, year)
