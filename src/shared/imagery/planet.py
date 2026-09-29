import calendar
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict


class MonthlyPeriod(BaseModel):
    start: date
    end: date

    @classmethod
    def from_month(cls, month: str) -> "MonthlyPeriod":
        start = date.fromisoformat(f"{month}-01")
        last_day = calendar.monthrange(start.year, start.month)[1]
        return cls(start=start, end=start.replace(day=last_day))


class PlanetImagery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["planet"] = "planet"
    period: MonthlyPeriod
