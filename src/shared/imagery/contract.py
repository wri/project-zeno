from datetime import date
from typing import ClassVar

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    def model_post_init(self, context) -> None:
        if type(self).__dict__.get("abstract", False):
            raise TypeError(
                f"{type(self).__name__} is abstract; build a specialist"
            )


class LayerPeriod(StrictModel):
    abstract: ClassVar[bool] = True

    start: date
    end: date

    def label(self) -> str:
        return f"{self.start} → {self.end}"


class RasterSource(StrictModel):
    tiles: list[str]
    bounds: tuple[float, float, float, float]
    minzoom: int
    maxzoom: int


class ImageryBase(StrictModel):
    abstract: ClassVar[bool] = True

    provider: str
    period: LayerPeriod
    tile_url: str
    aoi_names: list[str]
    layer_id: str

    def label(self) -> str:
        return f"{self.provider} {self.period.label()}"
