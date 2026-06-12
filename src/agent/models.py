from pydantic import BaseModel, Field


class ImageryState(BaseModel):
    """State model for satellite imagery layers."""

    tile_url: str = Field(..., description="Tile URL for the imagery layer")
    tilejson_url: str = Field(
        ..., description="TileJSON URL for the imagery layer"
    )
    mosaic_id: str = Field(..., description="ID of the mosaic")
    item_count: int = Field(..., description="Number of scenes in the mosaic")
    date_start: str = Field(
        ..., description="Start date of imagery (ISO format)"
    )
    date_end: str = Field(..., description="End date of imagery (ISO format)")
    target_date: str = Field(
        ..., description="Target date requested (ISO format)"
    )
    window_days: int = Field(..., description="Search window in days")
    max_cloud_cover: int = Field(..., description="Max cloud cover percentage")
    aoi_names: list[str] = Field(
        ..., description="Names of selected areas of interest"
    )
