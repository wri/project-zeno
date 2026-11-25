from typing import Literal, Optional

from pydantic import BaseModel, Field


class ImageryState(BaseModel):
    """State model for satellite imagery layers."""

    provider: Literal["sentinel-2", "planet"] = Field(
        "sentinel-2", description="Imagery provider"
    )
    render: Literal["tiler", "client"] = Field(
        "tiler",
        description=(
            "How the frontend draws the layer. 'tiler': from tile_url "
            "(Planet, and legacy Sentinel-2 mosaics). 'client': the browser "
            "searches and renders the Sentinel-2 scenes itself from the "
            "recipe token in mosaic_id; there is no tile_url."
        ),
    )
    tile_url: Optional[str] = Field(
        None, description="Tile URL for the imagery layer (tiler only)"
    )
    tilejson_url: Optional[str] = Field(
        None, description="TileJSON URL for the imagery layer"
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
    item_count: Optional[int] = Field(
        None, description="Number of scenes in the mosaic"
    )
    start_date: Optional[str] = Field(
        None, description="Inclusive start date of selected imagery, ISO"
    )
    end_date: Optional[str] = Field(
        None, description="Inclusive end date of selected imagery, ISO"
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
