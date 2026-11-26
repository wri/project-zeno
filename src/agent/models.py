from typing import Literal, Optional

from pydantic import BaseModel, Field


class ImageryState(BaseModel):
    """State model for satellite imagery layers."""

    provider: Literal["sentinel-2", "planet"] = Field(
        "sentinel-2", description="Imagery provider"
    )
    tile_url: Optional[str] = Field(
        None,
        description=(
            "Tile URL (Planet). Sentinel-2 has none: the browser searches "
            "and draws the scenes from the recipe token in mosaic_id."
        ),
    )
    bounds: Optional[list[float]] = Field(
        None, description="Layer bounds as [west, south, east, north]"
    )
    min_zoom: Optional[int] = Field(None, description="Minimum tile zoom")
    max_zoom: Optional[int] = Field(None, description="Maximum tile zoom")
    mosaic_id: str = Field(
        ...,
        description=(
            "ID of the imagery. For Sentinel-2, the recipe token "
            "(src/shared/imagery_recipe.py) the frontend decodes."
        ),
    )
    start_date: Optional[str] = Field(
        None, description="Start of the Planet month, ISO"
    )
    end_date: Optional[str] = Field(
        None, description="End of the Planet month, ISO"
    )
    target_date: Optional[str] = Field(
        None, description="Target date requested (ISO format)"
    )
    window_days: Optional[int] = Field(
        None, description="Search window in days"
    )
    max_cloud_cover: Optional[int] = Field(
        None, description="Max cloud cover percentage"
    )
    aoi_names: list[str] = Field(
        ..., description="Names of selected areas of interest"
    )
