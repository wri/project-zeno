"""API response and request models."""

from datetime import date
from typing import Optional

from pydantic import BaseModel


class MosaicCreateResponse(BaseModel):
    """Response model for mosaic creation endpoint.

    item_count / date_start / date_end / cloud_cover stats are absent only if
    the mosaic was written before these fields were added or the JSON is
    unreadable.
    """

    mosaic_id: str
    item_count: Optional[int] = None
    date_start: Optional[date] = None
    date_end: Optional[date] = None
    mean_cloud_cover: Optional[float] = None
    min_cloud_cover: Optional[float] = None
    max_cloud_cover: Optional[float] = None
