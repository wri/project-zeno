"""Send custom areas to the analytics API's custom AOI store.

The analytics pipelines batch-process custom areas from that store. The
database stays the source of truth, so a failed request is logged and the
user's request still succeeds.
"""

import json
from typing import Optional, Protocol, Sequence
from uuid import UUID

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.datasets.handlers.analytics_handler import analytics_api_headers
from src.api.data_models import AoiOrm
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class CustomAoiStore(Protocol):
    async def save(self, aois: list[dict]) -> None: ...

    async def delete(self, aoi_id: str) -> None: ...


class AnalyticsCustomAoiStore:
    def __init__(
        self,
        base_url: str,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        batch_size: int = 500,
        timeout_seconds: float = 60,
    ):
        self.url = base_url + "/v0/custom_aois"
        self.transport = transport
        self.batch_size = batch_size
        self.timeout_seconds = timeout_seconds

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self.timeout_seconds, transport=self.transport
        )

    async def save(self, aois: list[dict]) -> None:
        async with self.client() as client:
            for start in range(0, len(aois), self.batch_size):
                response = await client.put(
                    self.url,
                    json={"aois": aois[start : start + self.batch_size]},
                    headers=analytics_api_headers(),
                )
                response.raise_for_status()

    async def delete(self, aoi_id: str) -> None:
        async with self.client() as client:
            response = await client.delete(
                f"{self.url}/{aoi_id}", headers=analytics_api_headers()
            )
            response.raise_for_status()


class CustomAoiAnalyticsService:
    def __init__(self, store: CustomAoiStore):
        self.store = store

    async def save(self, session: AsyncSession, area_ids: Sequence[UUID]):
        src_ids = [str(area_id) for area_id in area_ids]
        rows = await session.execute(
            select(
                AoiOrm.source_id,
                AoiOrm.name,
                AoiOrm.created_by,
                func.ST_AsGeoJSON(AoiOrm.geometry).label("geometry"),
            ).where(
                AoiOrm.source == "custom",
                AoiOrm.source_id.in_(src_ids),
                AoiOrm.is_deprecated.is_(False),
            )
        )
        aois = [
            {
                "id": row.source_id,
                "name": row.name,
                "user_id": row.created_by,
                "geometry": json.loads(row.geometry),
            }
            for row in rows
        ]
        if not aois:
            return
        try:
            await self.store.save(aois)
        except httpx.HTTPError as error:
            logger.warning(
                "custom_aoi_analytics_failed",
                area_ids=src_ids,
                error=repr(error),
            )

    async def delete(self, area_id: UUID):
        try:
            await self.store.delete(str(area_id))
        except httpx.HTTPError as error:
            logger.warning(
                "custom_aoi_analytics_failed",
                area_ids=[str(area_id)],
                error=repr(error),
            )
