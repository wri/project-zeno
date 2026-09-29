from datetime import date, timedelta


class SearchWindowPeriod:
    def __init__(self, start: date, end: date):
        self.start = start
        self.end = end

    @classmethod
    def from_search(
        cls, target_date: date, window_days: int, today: date
    ) -> "SearchWindowPeriod":
        window = timedelta(days=window_days)
        return cls(target_date - window, min(target_date + window, today))
