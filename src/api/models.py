"""API response and request models."""

from datetime import date
from typing import Optional

from pydantic import BaseModel


class MosaicCreateResponse(BaseModel):
    """Response model for mosaic creation endpoint.

    The build-time stats are served from the metadata sidecar on a cache
    hit; they are absent only for mosaics written before the sidecar
    existed. mean_cloud_cover is the observed mean across the mosaic's
    scenes, not the search threshold.
    """

    mosaic_id: str
    item_count: Optional[int] = None
    date_start: Optional[date] = None
    date_end: Optional[date] = None
    mean_cloud_cover: Optional[float] = None
