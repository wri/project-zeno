from datetime import date

from pydantic import BaseModel


class LayerPeriod(BaseModel):
    start: date
    end: date
