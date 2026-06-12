"""API response and request models."""

from datetime import date

from pydantic import BaseModel


class MosaicCreateResponse(BaseModel):
    """Response model for mosaic creation endpoint."""

    mosaic_id: str
    item_count: int
    date_start: date
    date_end: date
