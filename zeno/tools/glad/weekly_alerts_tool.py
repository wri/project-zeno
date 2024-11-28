import os
from typing import Optional
from urllib.parse import quote

import pandas as pd
import requests
from dotenv import load_dotenv
from langchain_core.tools import tool
from pydantic import BaseModel, Field

# Load environment variables
load_dotenv(".env")


class GladAlertsInput(BaseModel):
    """Input schema for forest fire alerts tool"""

    iso: str = Field(
        description="ISO 3-letter country code (e.g., 'MDG' for Madagascar)"
    )
    adm1: str = Field(description="Administrative level 1 ID")
    adm2: str = Field(description="Administrative level 2 ID")
    year: int = Field(description="Year for which to fetch alerts", ge=2015, le=2024)
    week: Optional[int] = Field(
        default=None,
        description="Specific week number (1-52) to fetch. If not provided, returns all weeks.",
        ge=1,
        le=52,
    )


@tool("glad-weekly-alerts-tool", args_schema=GladAlertsInput, return_direct=True)
def glad_weekly_alerts_tool(
    iso: str, adm1: str, adm2: str, year: int, week: Optional[int] = None
) -> str:
    """Fetch forest fire alerts for a specific administrative region and time period."""
    print("---GLAD-WEEKLY-ALERTS-TOOL---")

    # Get credentials from environment variables
    headers = {
        "x-api-key": os.getenv("WRI_API_KEY"),
        "Authorization": f"Bearer {os.getenv('WRI_BEARER_TOKEN')}",
    }

    # Construct SQL query
    sql = f"""
    SELECT iso, adm1, adm2, alert__year, alert__week,
           SUM(alert__count) AS alert_sum,
           SUM(alert_area__ha) AS area_sum
    FROM result_table
    WHERE iso='{iso}'
    AND adm1='{adm1}'
    AND adm2='{adm2}'
    AND alert__year={year}
    """

    if week is not None:
        sql += f" AND alert__week={week}"

    sql += " GROUP BY iso, adm1, adm2, alert__year, alert__week"

    # Make API request
    url = f"https://data-api.globalforestwatch.org/dataset/gadm__glad__adm2_weekly_alerts/latest/query?sql={quote(sql)}"

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()

        if not data.get("data"):
            return (
                f"No GLAD alerts found for the specified region and time period:\n"
                f"Country: {iso}, ADM1: {adm1}, ADM2: {adm2}, Year: {year}"
                + (f", Week: {week}" if week else "")
            )
        else:
            return data

        # Process the data
        alerts_data = pd.DataFrame(data["data"])
        total_alerts = alerts_data["alert_sum"].sum()
        total_area = alerts_data["area_sum"].sum()

        # Format response
        response_parts = [
            "GLAD Alerts Summary:",
            f"Location: {iso}, ADM1: {adm1}, ADM2: {adm2}",
            f"Year: {year}" + (f", Week: {week}" if week else ""),
            f"Total Alerts: {total_alerts:,}",
            f"Total Area Affected: {total_area:,.2f} hectares",
            "\nWeekly Breakdown:",
        ]

        for _, row in alerts_data.sort_values("alert__week").iterrows():
            response_parts.append(
                f"Week {row['alert__week']}: "
                f"{row['alert_sum']:,} alerts, "
                f"{row['area_sum']:.2f} ha"
            )

        return "\n".join(response_parts)

    except requests.exceptions.RequestException as e:
        return f"Error fetching GLAD alerts: {str(e)}"
    except Exception as e:
        return f"Error processing GLAD alerts data: {str(e)}"


if __name__ == "__main__":
    test_query = {"iso": "MDG", "adm1": "3", "adm2": "4", "year": 2021}

    result = glad_weekly_alerts_tool.invoke(test_query)
    print(result)
