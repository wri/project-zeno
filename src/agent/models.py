from typing import Optional

from pydantic import BaseModel, Field


class ImageryState(BaseModel):
    """State model for satellite imagery layers."""

    tile_url: str = Field(..., description="Tile URL for the imagery layer")
    tilejson_url: str = Field(
        ..., description="TileJSON URL for the imagery layer"
    )
    mosaic_id: str = Field(..., description="ID of the mosaic")
    item_count: Optional[int] = Field(
        None, description="Number of scenes in the mosaic"
    )
    date_start: Optional[str] = Field(
        None, description="Start date of imagery, ISO"
    )
    date_end: Optional[str] = Field(
        None, description="End date of imagery, ISO"
    )
    mean_cloud_cover: Optional[float] = Field(
        None, description="Mean cloud cover across scenes (%)"
    )
    min_cloud_cover: Optional[float] = Field(
        None, description="Minimum cloud cover across scenes (%)"
    )
    # Suffixed (unlike mean/min) because max_cloud_cover below is already
    # taken by the pre-existing search-threshold field; persisted dashboard
    # widget configs rely on that field keeping its original meaning.
    max_cloud_cover_observed: Optional[float] = Field(
        None, description="Highest observed cloud cover across scenes (%)"
    )
    target_date: str = Field(
        ..., description="Target date requested (ISO format)"
    )
    window_days: int = Field(..., description="Search window in days")
    max_cloud_cover: int = Field(..., description="Max cloud cover percentage")
    aoi_names: list[str] = Field(
        ..., description="Names of selected areas of interest"
    )
