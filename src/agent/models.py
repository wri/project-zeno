from typing import Optional

from pydantic import BaseModel, Field


class ImageryState(BaseModel):
    """State model for satellite imagery layers.

    item_count / date_start / date_end are only known when the mosaic is
    built, so they are None on a cache hit (mosaic already in S3).
    """

    tile_url: str = Field(..., description="Tile URL for the imagery layer")
    tilejson_url: str = Field(
        ..., description="TileJSON URL for the imagery layer"
    )
    mosaic_id: str = Field(..., description="ID of the mosaic")
    item_count: Optional[int] = Field(
        None, description="Number of scenes in the mosaic (None on cache hit)"
    )
    date_start: Optional[str] = Field(
        None, description="Start date of imagery, ISO (None on cache hit)"
    )
    date_end: Optional[str] = Field(
        None, description="End date of imagery, ISO (None on cache hit)"
    )
    target_date: str = Field(
        ..., description="Target date requested (ISO format)"
    )
    window_days: int = Field(..., description="Search window in days")
    max_cloud_cover: int = Field(..., description="Max cloud cover percentage")
    mean_cloud_cover: Optional[float] = Field(
        None,
        description=(
            "Observed mean cloud cover across the mosaic's scenes, percent "
            "(None when the cached mosaic predates the metadata sidecar)"
        ),
    )
    aoi_names: list[str] = Field(
        ..., description="Names of selected areas of interest"
    )
