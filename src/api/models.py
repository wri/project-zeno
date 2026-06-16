"""API response and request models."""

from datetime import date
from typing import Optional

from pydantic import BaseModel


class MosaicCreateResponse(BaseModel):
    """Response model for mosaic creation endpoint.

    item_count / date_start / date_end are absent on a cache hit, where the
    mosaic is served from S3 without rerunning the (build-time) STAC search.
    """

    mosaic_id: str
    item_count: Optional[int] = None
    date_start: Optional[date] = None
    date_end: Optional[date] = None
