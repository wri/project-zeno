import calendar
from datetime import date


class MonthlyPeriod:
    def __init__(self, start: date, end: date):
        self.start = start
        self.end = end

    @classmethod
    def from_month(cls, month: str) -> "MonthlyPeriod":
        start = date.fromisoformat(f"{month}-01")
        last_day = calendar.monthrange(start.year, start.month)[1]
        return cls(start, start.replace(day=last_day))
