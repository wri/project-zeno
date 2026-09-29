from datetime import date

from pydantic import BaseModel


class LayerPeriod(BaseModel):
    start: date
    end: date

    def model_post_init(self, context) -> None:
        if type(self) is LayerPeriod:
            raise TypeError(
                "LayerPeriod is abstract; build a specialist period"
            )
