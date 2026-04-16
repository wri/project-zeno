"""HTTP client for the FAO FRA 2025 public API.

Endpoint used: GET /explorer/data (published, open-access data)
Swagger spec: https://fra-data.fao.org/api-docs/swagger.json
"""

from typing import Optional

import httpx

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

BASE_URL = "https://fra-data.fao.org/api"
ASSESSMENT_NAME = "fra"
CYCLE_NAME = "2025"
TIMEOUT_SECONDS = 15.0

# FRA reporting years (discrete snapshots, not interpolated).
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


def _parse_response(
    body: dict,
    iso3: str,
    table: str,
    year: Optional[int],
) -> list[dict]:
    """Flatten the nested FAO response into a list of records.

    Each record: {"year": int, "variable": str, "value": float | None, "odp": bool, "country": str}

    Raises FAODataNotFoundError when the country or table is absent.
    """
    try:
        cycle_data = body.get(ASSESSMENT_NAME, {})
        # The cycle key may be "2025" or "latest" — take the first available cycle.
        if not cycle_data:
            raise FAODataNotFoundError(f"No FRA data returned for {iso3}.")
        cycle_key = next(iter(cycle_data))
        country_data = cycle_data[cycle_key].get(iso3)
    except (KeyError, StopIteration) as exc:
        raise FAODataNotFoundError(f"No FRA data returned for {iso3}.") from exc

    if not country_data:
        raise FAODataNotFoundError(
            f"FRA 2025 does not include data for country '{iso3}'. "
            "You can browse available countries at https://fra-data.fao.org."
        )

    table_data = country_data.get(table)
    if not table_data:
        raise FAODataNotFoundError(
            f"FRA 2025 does not include data for table '{table}' for {iso3}. "
            "You can browse available variables at https://fra-data.fao.org."
        )

    records = []
    for year_str, variables in table_data.items():
        try:
            row_year = int(year_str)
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
        variables: List of variable names to filter on (empty = all variables).
        year: Optional reporting year to filter (must be one of FRA_REPORTING_YEARS).

    Returns:
        List of records: [{"year", "variable", "value", "odp", "country"}, ...]

    Raises:
        FAOAPIError: Network failure, timeout, or HTTP 4xx/5xx.
        FAODataNotFoundError: Country or table absent from FRA 2025.
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

    logger.info(f"FAO-CLIENT: GET /explorer/data iso={iso3} table={table} year={year}")

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.get(f"{BASE_URL}/explorer/data", params=params)
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
            f"FAO FRA API returned a server error ({response.status_code}). "
            "Please try again later."
        )
    if response.status_code == 401:
        raise FAOAPIError(
            "FAO FRA API requires authentication for this endpoint. "
            "Please contact the GNW team."
        )
    if response.status_code >= 400:
        raise FAODataNotFoundError(
            f"FAO FRA API returned {response.status_code} for {iso3} / {table}. "
            "The country or variable may not be available in FRA 2025."
        )

    try:
        body = response.json()
    except Exception as exc:
        raise FAOAPIError(
            "FAO FRA API returned an unexpected response format."
        ) from exc

    return _parse_response(body, iso3, table, year)
