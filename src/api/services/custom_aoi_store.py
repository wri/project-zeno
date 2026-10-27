"""Keep the analytics API's custom AOI store in step with ``custom_areas``.

The analytics pipelines batch-process custom areas from that store. The
database stays the source of truth, so a failed sync is logged and the user's
request still succeeds.
"""

import json
from typing import Optional, Protocol, Sequence
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.datasets.handlers.analytics_handler import analytics_api_headers
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


# Reads the dissolved geometry from the mirrored aois row.
CUSTOM_AOIS_SQL = """
    SELECT a.source_id, a.name, a.created_by, u.email,
           ST_AsGeoJSON(a.geometry) AS geometry
    FROM aois a
    JOIN users u ON u.id = a.created_by
    WHERE a.source = 'custom' AND a.source_id = ANY(:src_ids)
      AND NOT a.is_deprecated
"""


class CustomAoiSync:
    def __init__(self, store: CustomAoiStore):
        self.store = store

    async def save(self, session: AsyncSession, area_ids: Sequence[UUID]):
        src_ids = [str(area_id) for area_id in area_ids]
        rows = await session.execute(
            text(CUSTOM_AOIS_SQL), {"src_ids": src_ids}
        )
        aois = [
            {
                "id": row.source_id,
                "name": row.name,
                "user_id": row.created_by,
                "email": row.email,
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
                "custom_aoi_sync_failed", area_ids=src_ids, error=repr(error)
            )

    async def delete(self, area_id: UUID):
        try:
            await self.store.delete(str(area_id))
        except httpx.HTTPError as error:
            logger.warning(
                "custom_aoi_sync_failed",
                area_ids=[str(area_id)],
                error=repr(error),
            )
