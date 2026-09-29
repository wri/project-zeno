from datetime import date

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LayerPeriod(BaseModel):
    start: date
    end: date

    def model_post_init(self, context) -> None:
        if type(self) is LayerPeriod:
            raise TypeError(
                "LayerPeriod is abstract; build a specialist period"
            )

    def label(self) -> str:
        return f"{self.start} → {self.end}"
