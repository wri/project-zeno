"""The live integrated alerts list of an area.

Nothing is written: each request is one analytics pull for one area and
period, and the analytics API caches identical pulls. The alerts widget on a
dashboard asks for its period and filters the rows on the client.
"""

import asyncio
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status

from src.agent.datasets.handlers.analytics_handler import AnalyticsHandler
from src.api.auth.dependencies import require_auth
from src.api.schemas import AlertsListRequest, AlertsListResponse, UserModel
from src.api.services.alerts_list import (
    AlertsListService,
    InvalidWindowError,
    UnexpectedAlertsDataError,
    UnsupportedAreaError,
)
from src.api.services.dashboard_alerts import AlertsUnavailableError
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()

# A table on a dashboard should not wait as long as a chat turn (the handler
# polls for up to 180 s). The analytics job keeps running after the timeout
# and its result is cached, so a retry is fast.
ALERTS_LIST_TIMEOUT_SECONDS = 60
# The upstream message can carry the analytics URL and payload, so the
# client gets this and the log gets the rest.
ALERTS_UNAVAILABLE_MESSAGE = (
    "Integrated alerts data is unavailable right now. Please try again in a "
    "moment."
)


def get_alerts_list_service() -> AlertsListService:
    return AlertsListService(AnalyticsHandler())


def get_today() -> date:
    return date.today()


def _unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=ALERTS_UNAVAILABLE_MESSAGE,
    )


@router.post("/api/alerts/list", response_model=AlertsListResponse)
async def list_alerts(
    body: AlertsListRequest,
    user: UserModel = Depends(require_auth),
    service: AlertsListService = Depends(get_alerts_list_service),
    today: date = Depends(get_today),
):
    """Integrated alerts in one area, one row per day with the high and
    highest confidence areas, newest first.

    The period defaults to the 30 days to today. It is clamped to the data
    and must not be longer than 365 days. Rows in the latest full alert week
    (Sunday to Saturday) are flagged `new`. `land_filter` restricts the rows
    and totals to alerts on natural lands or natural forests. `data_to` is
    the latest alert date in the data, of any confidence, which can be before
    `end_date`; null when the period has no data.

    422 when the area type has no alerts analysis or the period is empty or
    too long. 502 with a fixed message when the analytics API fails or does
    not answer within 60 seconds; nothing is cached on this side.
    """
    aoi = {
        "source": body.source,
        "src_id": body.src_id,
        "subtype": body.subtype,
    }
    request = {
        **aoi,
        "start_date": str(body.start_date),
        "end_date": str(body.end_date),
        "land_filter": body.land_filter,
    }
    try:
        alerts = await asyncio.wait_for(
            service.list(
                aoi,
                body.start_date,
                body.end_date,
                today=today,
                land_filter=body.land_filter,
            ),
            timeout=ALERTS_LIST_TIMEOUT_SECONDS,
        )
    except (UnsupportedAreaError, InvalidWindowError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        )
    except UnexpectedAlertsDataError:
        logger.exception("alerts_list_unexpected_data", **request)
        raise _unavailable()
    except AlertsUnavailableError as error:
        logger.warning("alerts_list_unavailable", error=str(error), **request)
        raise _unavailable()
    except TimeoutError:
        logger.warning(
            "alerts_list_timeout",
            timeout_seconds=ALERTS_LIST_TIMEOUT_SECONDS,
            **request,
        )
        raise _unavailable()
    return AlertsListResponse.model_validate(alerts, from_attributes=True)
