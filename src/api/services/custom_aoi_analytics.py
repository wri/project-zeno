"""Send custom areas to the analytics API, which batch-processes them.

Failures are logged rather than raised, since the database is the source of
truth.
"""

import json
import time
from typing import Optional
from uuid import UUID

import httpx

from src.agent.datasets.handlers.analytics_handler import analytics_api_headers
from src.api.data_models import CustomAreaOrm
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


def custom_aoi_payload(area: CustomAreaOrm) -> dict:
    polygons = []
    for part in area.geometries:
        geometry = json.loads(part)
        if geometry["type"] == "MultiPolygon":
            polygons.extend(geometry["coordinates"])
        else:
            polygons.append(geometry["coordinates"])
    return {
        "id": str(area.id),
        "name": area.name,
        "user_id": area.user_id,
        "geometry": {"type": "MultiPolygon", "coordinates": polygons},
    }


class CustomAoiAnalyticsService:
    def __init__(
        self,
        base_url: str,
        enabled: bool = True,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        timeout_seconds: float = 60,
    ):
        self.url = base_url + "/v0/custom_aois"
        self.enabled = enabled
        self.transport = transport
        self.timeout_seconds = timeout_seconds

    async def save(self, aois: list[dict]) -> None:
        await self.send(
            "PUT", self.url, [aoi["id"] for aoi in aois], json={"aois": aois}
        )

    async def delete(self, area_id: UUID) -> None:
        await self.send("DELETE", f"{self.url}/{area_id}", [str(area_id)])

    async def send(
        self, method: str, url: str, aoi_ids: list[str], **kwargs
    ) -> None:
        if not self.enabled:
            return
        started = time.monotonic()
        status_code, detail = None, None
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds, transport=self.transport
            ) as client:
                response = await client.request(
                    method, url, headers=analytics_api_headers(), **kwargs
                )
            status_code = response.status_code
            outcome = "http_error" if response.is_error else "ok"
            if response.is_error:
                # Error bodies can echo whole geometries back.
                detail = response.text[:1000]
        except httpx.HTTPError as error:
            outcome, detail = "network_error", repr(error)
        log = logger.info if outcome == "ok" else logger.warning
        log(
            "custom_aoi_analytics_request",
            method=method,
            outcome=outcome,
            status_code=status_code,
            aoi_ids=aoi_ids,
            duration_ms=round((time.monotonic() - started) * 1000),
            detail=detail,
        )
