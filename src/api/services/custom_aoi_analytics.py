"""Send custom areas to the analytics API, which batch-processes them.

Failures are logged rather than raised, since the database is the source of
truth.
"""

import json
from typing import Optional, Protocol
from uuid import UUID

import httpx

from src.agent.datasets.handlers.analytics_handler import analytics_api_headers
from src.api.data_models import CustomAreaOrm
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class CustomAoiStoreError(Exception):
    def __init__(self, detail: str, status_code: Optional[int] = None):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


class CustomAoiStore(Protocol):
    async def save(self, aois: list[dict]) -> None: ...

    async def delete(self, aoi_id: str) -> None: ...


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


class AnalyticsCustomAoiStore:
    def __init__(
        self,
        base_url: str,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        timeout_seconds: float = 60,
        max_detail_length: int = 1000,
    ):
        self.url = base_url + "/v0/custom_aois"
        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self.max_detail_length = max_detail_length

    async def request(self, method: str, url: str, **kwargs) -> None:
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds, transport=self.transport
            ) as client:
                response = await client.request(
                    method, url, headers=analytics_api_headers(), **kwargs
                )
        except httpx.HTTPError as error:
            raise CustomAoiStoreError(repr(error)) from error
        if response.is_error:
            raise CustomAoiStoreError(
                response.text[: self.max_detail_length], response.status_code
            )

    async def save(self, aois: list[dict]) -> None:
        await self.request("PUT", self.url, json={"aois": aois})

    async def delete(self, aoi_id: str) -> None:
        await self.request("DELETE", f"{self.url}/{aoi_id}")


class CustomAoiAnalyticsService:
    def __init__(self, store: CustomAoiStore):
        self.store = store

    async def save(self, aois: list[dict]) -> None:
        try:
            await self.store.save(aois)
        except CustomAoiStoreError as error:
            self.log_failure([aoi["id"] for aoi in aois], error)

    async def delete(self, area_id: UUID) -> None:
        try:
            await self.store.delete(str(area_id))
        except CustomAoiStoreError as error:
            self.log_failure([str(area_id)], error)

    def log_failure(self, aoi_ids: list[str], error: CustomAoiStoreError):
        logger.warning(
            "custom_aoi_analytics_failed",
            aoi_ids=aoi_ids,
            status_code=error.status_code,
            detail=error.detail,
        )
