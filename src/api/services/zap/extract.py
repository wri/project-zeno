"""Read the place, the time and the canopy cover of a zap request with
Clairic, an extraction model on the OpenRouter extractions API.

An extraction model does not select options. It gets a text and named, typed
fields, and returns a value for each field, or null when the text does not
have it. So it reads values that the option lists of jev cannot hold, for
example "from 2015 to 2020", "March 2026" or "12% canopy cover".

Ported from stac-zap (`src/zap/extract.ts`). The tests of that port are in
`stac-zap/docs/decision-models.md` ("Test 3: extraction models"). The rules
that the port keeps:

- Two calls at the same time. Call A reads the request only and gives the
  place and the canopy cover. Call B reads the app context, today's date and
  the request, and gives the time. In one call, a number such as "12%"
  moved into the dates.
- `when` holds the words of the time. When it is null, the request names no
  time, also if the model gives dates.
- Code does the calendar: a season, a quarter, a half year, "the last 3
  months", "recent" and "all years" get their range from code, from the
  words in `when`.
"""

import asyncio
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal, Optional

import httpx

from src.api.config import APISettings
from src.api.services.zap.jev import CONTEXT

# A date range. `(None, None)` is the whole record of the dataset.
Range = tuple[Optional[str], Optional[str]]

PLACE = (
    "The name of the area to show on the map. An area can be a country, a "
    "state, a province, a district, a city, a protected area, a national "
    "park, a key biodiversity area or indigenous land. If the request names "
    "a protected area or a park inside a larger area, give the name of the "
    "protected area or park. Include the larger area that the request gives "
    "with the name, e.g. 'Sara, Bolivia' or 'Pocho in Cordoba'. The name of "
    "a dataset, of a forest type or of an event is not an area. If the "
    "request says 'here', 'this area' or 'the map', give those words."
)

CANOPY = (
    "The minimum tree canopy cover, only if the request names a canopy "
    "cover or a tree cover density threshold, e.g. 'at 50% canopy' or "
    "'canopy density above 10%'. Other percentages are not the canopy cover."
)

WHEN = (
    "The words of the request that name a time, a date or a period, e.g. "
    "'in 2021', 'from 2015 to 2020', 'March 2026', 'last year', 'recent' "
    "or 'since 2015'. A dataset name or a place is not a time."
)

START = (
    "The first day of the time period the request asks for. For a day, "
    "that day; for a month, the 1st of that month; for a year, 1 January."
)

END = (
    "The last day of the time period the request asks for. For a day, that "
    "day; for a month, the last day of that month; for a year, 31 December. "
    "If the period runs up to now, the reference date."
)

CLOUD = (
    "The maximum cloud cover of satellite imagery, only if the request "
    "names a cloud cover limit, e.g. 'less than 10% clouds' or 'cloud-free "
    "under 5%'. Other percentages are not the cloud cover."
)

CALL_A = {
    "place": {"type": "text", "instructions": PLACE},
    "canopy": {"type": "number", "unit": "percent", "instructions": CANOPY},
}
# Call A on a dashboard: the area is the area of the dashboard, so there is
# no place field. The cloud cover is for imagery widgets.
CALL_A_DASHBOARD = {
    "canopy": {"type": "number", "unit": "percent", "instructions": CANOPY},
    "cloud": {"type": "number", "unit": "percent", "instructions": CLOUD},
}
CALL_B = {
    "when": {"type": "text", "instructions": WHEN},
    "start": {"type": "date", "instructions": START},
    "end": {"type": "date", "instructions": END},
}


RETRIES = 1
RETRY_STATUS = {429, 500, 502, 503, 504}
RETRY_PAUSE_SECONDS = 0.3


class ExtractError(RuntimeError):
    """Clairic could not answer."""


@dataclass
class PlaceExtraction:
    """What call A read. None means "not in the request"."""

    place: Optional[str]
    place_probability: float
    canopy: Optional[float]
    canopy_probability: float
    answers: dict[str, Any] = field(default_factory=dict)


@dataclass
class NumberExtraction:
    """What call A read on a dashboard. None means "not in the request"."""

    canopy: Optional[float]
    canopy_probability: float
    cloud: Optional[float]
    cloud_probability: float
    answers: dict[str, Any] = field(default_factory=dict)


@dataclass
class TimeExtraction:
    """What call B read.

    `range` is None when the request names no time, and `(None, None)` for
    the whole record. `source` is "code" when a calendar rule made the
    range from the words in `when`. `probability` is the probability of the
    answer: that the request names this time, or that it names no time.
    """

    when: Optional[str]
    range: Optional[Range]
    source: Literal["clairic", "code"]
    probability: float
    answers: dict[str, Any] = field(default_factory=dict)


NOW = re.compile(r"(?:right )?(?:today|now|currently|at the moment)", re.I)


def time_state(prompt: str, today: date) -> str:
    """The text that call B reads: the app, today's date and the request.
    Without the app context, the dates were worse in the stac-zap tests."""
    return f"{CONTEXT}\n\nToday is {today}.\n\nUser request: {prompt}"


async def extract_fields(
    state: str,
    fields: dict[str, dict],
    reference_date: Optional[date] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, dict]:
    """One extraction call; return the answer of each field.

    Raises:
        ExtractError: When the key is missing, the call fails, or the
            answers do not hold all the fields.
    """
    if not APISettings.openrouter_api_key:
        raise ExtractError("OPENROUTER_API_KEY is not set")
    payload: dict[str, Any] = {
        "model": APISettings.extract_model,
        "state": state,
        "fields": fields,
    }
    if reference_date is not None:
        # The API rejects a reference date with no date field.
        payload["reference_date"] = str(reference_date)
    headers = {"Authorization": f"Bearer {APISettings.openrouter_api_key}"}
    owned = client is None
    client = client or httpx.AsyncClient(
        timeout=APISettings.extract_timeout_seconds
    )
    try:
        for attempt in range(1 + RETRIES):
            response = await client.post(
                APISettings.extract_url, json=payload, headers=headers
            )
            if response.status_code not in RETRY_STATUS or attempt == RETRIES:
                break
            # "Capacity temporarily exceeded": one more try after a pause.
            await asyncio.sleep(RETRY_PAUSE_SECONDS)
    except httpx.HTTPError as exc:
        raise ExtractError(f"extraction call failed: {exc!r}") from exc
    finally:
        if owned:
            await client.aclose()
    if response.status_code != 200:
        raise ExtractError(
            f"extraction call failed ({response.status_code}): "
            f"{response.text[:300]}"
        )
    try:
        answers = response.json().get("answers") or {}
    except ValueError as exc:
        raise ExtractError("extraction answer is not JSON") from exc
    missing = [
        name for name in fields if not isinstance(answers.get(name), dict)
    ]
    if missing:
        raise ExtractError(f"extraction gave no answer for {missing}")
    return answers


def _value(answer: Optional[dict]) -> Any:
    return None if not answer else answer.get("value")


def _text(answer: Optional[dict]) -> Optional[str]:
    value = _value(answer)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _probability(answer: Optional[dict]) -> float:
    """The probability that the value is in the request."""
    if not answer:
        return 0.0
    p_null = answer.get("p_null")
    if isinstance(p_null, (int, float)):
        return round(1 - float(p_null), 3)
    return float(answer.get("confidence") or 0.0)


def _percent(answer: Optional[dict]) -> Optional[float]:
    value = _value(answer)
    if not isinstance(value, (int, float)) or not 0 < value <= 100:
        return None
    return float(value)


async def extract_numbers(prompt: str) -> NumberExtraction:
    """Call A on a dashboard: the canopy cover and the cloud cover, from
    the request only."""
    answers = await extract_fields(prompt, CALL_A_DASHBOARD)
    return NumberExtraction(
        canopy=_percent(answers["canopy"]),
        canopy_probability=_probability(answers["canopy"]),
        cloud=_percent(answers["cloud"]),
        cloud_probability=_probability(answers["cloud"]),
        answers=answers,
    )


async def extract_place(prompt: str) -> PlaceExtraction:
    """Call A: the place and the canopy cover, from the request only."""
    answers = await extract_fields(prompt, CALL_A)
    canopy = _value(answers["canopy"])
    if not isinstance(canopy, (int, float)) or not 0 < canopy <= 100:
        canopy = None
    return PlaceExtraction(
        place=_text(answers["place"]),
        place_probability=_probability(answers["place"]),
        canopy=float(canopy) if canopy is not None else None,
        canopy_probability=_probability(answers["canopy"]),
        answers=answers,
    )


async def extract_time(prompt: str, today: date) -> TimeExtraction:
    """Call B: the time, from the app context, today's date and the request.

    Raises:
        ExtractError: Also when the answers make no range, e.g. an end with
            no start, so that the planner uses the jev period.
    """
    answers = await extract_fields(
        time_state(prompt, today), CALL_B, reference_date=today
    )
    when = _text(answers["when"])
    if when is not None and NOW.fullmatch(when):
        # "today" or "now" alone names no period of the data.
        when = None
    if when is None:
        # The probability that the request names no time.
        no_time = 1 - _probability(answers["when"])
        return TimeExtraction(
            None, None, "clairic", round(no_time, 3), answers
        )
    probability = _probability(answers["when"])
    rule = calendar_range(when, today)
    if rule is not None:
        return TimeExtraction(when, rule, "code", probability, answers)
    start = _iso(_value(answers["start"]))
    end = _iso(_value(answers["end"]))
    if start is None:
        raise ExtractError(f"no start date for '{when}'")
    if end is None:
        end = str(today)
    if start > end:
        raise ExtractError(f"start {start} is after end {end} for '{when}'")
    return TimeExtraction(when, (start, end), "clairic", probability, answers)


async def extract(
    prompt: str, today: date
) -> tuple[PlaceExtraction | BaseException, TimeExtraction | BaseException]:
    """Both calls at the same time. A failed call gives its exception."""
    place, time = await asyncio.gather(
        extract_place(prompt),
        extract_time(prompt, today),
        return_exceptions=True,
    )
    return place, time


async def extract_dashboard(
    prompt: str, today: date
) -> tuple[NumberExtraction | BaseException, TimeExtraction | BaseException]:
    """Call A on a dashboard and call B, at the same time. A failed call
    gives its exception."""
    numbers, time = await asyncio.gather(
        extract_numbers(prompt),
        extract_time(prompt, today),
        return_exceptions=True,
    )
    return numbers, time


def _iso(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    try:
        return str(date.fromisoformat(value[:10]))
    except ValueError:
        return None


# --- The calendar rules -----------------------------------------------------


def _month_end(year: int, month: int) -> date:
    first_next = date(year + month // 12, month % 12 + 1, 1)
    return first_next - timedelta(days=1)


def _shift_months(day: date, months: int) -> date:
    """`day` moved back by `months`, on the same day of the month or the
    last day of a shorter month."""
    index = day.year * 12 + day.month - 1 - months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(day.day, _month_end(year, month).day))


SEASONS = {"spring": 3, "summer": 6, "autumn": 9, "fall": 9, "winter": 12}


def season_range(words: str, today: date) -> Optional[Range]:
    """A meteorological season of the northern hemisphere, e.g. "winter
    2024" (December 2023 to February 2024) or "last summer". With no year,
    the most recent season that has started."""
    m = re.search(r"\b(spring|summer|autumn|fall|winter)\b", words, re.I)
    if not m:
        return None
    first_month = SEASONS[m.group(1).lower()]

    def span(year: int) -> tuple[date, date]:
        # Winter of a year starts in December of the year before.
        start_year = year - 1 if first_month == 12 else year
        start = date(start_year, first_month, 1)
        end_month = (first_month + 1) % 12 + 1
        end_year = start_year + (1 if end_month < first_month else 0)
        return start, _month_end(end_year, end_month)

    named = re.search(r"\b(\d{4})\b", words)
    if named:
        start, end = span(int(named.group(1)))
    else:
        start, end = span(today.year)
        if start > today:
            start, end = span(today.year - 1)
    return str(start), str(end)


QUARTERS = {
    "first": 1, "1st": 1, "second": 2, "2nd": 2,
    "third": 3, "3rd": 3, "fourth": 4, "4th": 4,
}  # fmt: skip


def quarter_range(words: str, today: date) -> Optional[Range]:
    """A quarter, e.g. "Q3 2021" or "the second quarter of 2022". With no
    year, the most recent quarter that has started."""
    m = re.search(
        r"\b(?:q([1-4])|(first|second|third|fourth|1st|2nd|3rd|4th)\s+quarter)\b",
        words,
        re.I,
    )
    if not m:
        return None
    q = int(m.group(1)) if m.group(1) else QUARTERS[m.group(2).lower()]
    named = re.search(r"\b(\d{4})\b", words)
    year = int(named.group(1)) if named else today.year
    if not named and date(year, 3 * q - 2, 1) > today:
        year -= 1
    return str(date(year, 3 * q - 2, 1)), str(_month_end(year, 3 * q))


def half_range(words: str, today: date) -> Optional[Range]:
    """A half year, e.g. "the second half of 2024" or "H1 2025". With no
    year, the most recent half that has started."""
    m = re.search(
        r"\b(?:h([12])|(first|second|1st|2nd)\s+half)\b", words, re.I
    )
    if not m:
        return None
    h = int(m.group(1)) if m.group(1) else QUARTERS[m.group(2).lower()]
    named = re.search(r"\b(\d{4})\b", words)
    year = int(named.group(1)) if named else today.year
    if not named and date(year, 6 * h - 5, 1) > today:
        year -= 1
    return str(date(year, 6 * h - 5, 1)), str(_month_end(year, 6 * h))


NUMBERS = {
    "a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}  # fmt: skip


def relative_range(words: str, today: date) -> Optional[Range]:
    """A period back from today, e.g. "the last 3 months" or "past week".
    A month or a year needs a number, because "last month" and "last year"
    can also mean the calendar month or year before."""
    m = re.search(
        r"\b(?:last|past)\s+(?:(\d+|a|one|two|three|four|five|six|seven|"
        r"eight|nine|ten|eleven|twelve)\s+)?(day|week|month|year)s?\b",
        words,
        re.I,
    )
    if not m:
        return None
    unit = m.group(2).lower()
    if not m.group(1) and unit in ("month", "year"):
        return None
    n = NUMBERS.get(m.group(1).lower(), 0) if m.group(1) else 1
    if m.group(1) and m.group(1).isdigit():
        n = int(m.group(1))
    if unit == "day":
        start = today - timedelta(days=n)
    elif unit == "week":
        start = today - timedelta(days=7 * n)
    elif unit == "month":
        start = _shift_months(today, n)
    else:
        start = _shift_months(today, 12 * n)
    return str(start), str(today)


def recent_range(words: str, today: date) -> Optional[Range]:
    """ "Recent" or "latest": the last 12 months, as the period option of
    the jev path ("Recent: the last 12 months")."""
    if not re.search(r"\b(recent|recently|latest)\b", words, re.I):
        return None
    return str(_shift_months(today, 12)), str(today)


# The words that can stand with years in a range of whole years. A word that
# is not here (a month, a day, a word of another language) leaves the range
# to the dates of the model.
YEAR_WORDS = {
    "in", "the", "year", "years", "of", "for", "during", "from", "to",
    "between", "and", "since", "after", "until", "till", "up", "through",
    "before", "starting", "onwards", "on", "a", "period", "only", "just",
    "年", "-", "–",
}  # fmt: skip


def year_range(words: str, today: date) -> Optional[Range]:
    """A range of whole years, e.g. "in 2019", "2015-2020", "between 2001
    and 2024", "since 2015" or "until 2010". Clairic often gives a wrong
    last day for these, e.g. 2026-12-12 for "in 2025"."""
    years = [int(y) for y in re.findall(r"(?<!\d)(\d{4})(?!\d)", words)]
    if not years:
        return None
    rest = re.sub(r"(?<!\d)\d{4}(?!\d)", " ", words.lower())
    tokens = re.findall(r"[-–]|[^\W\d_]+|\S", rest)
    if any(t not in YEAR_WORDS for t in tokens):
        return None
    if len(years) >= 2:
        return f"{min(years)}-01-01", f"{max(years)}-12-31"
    year = years[0]
    if re.search(r"\b(since|after|from|starting)\b", rest):
        first = year + 1 if re.search(r"\bafter\b", rest) else year
        return f"{first}-01-01", str(today)
    if re.search(r"\b(until|till|up|through|before)\b", rest):
        last = year - 1 if re.search(r"\bbefore\b", rest) else year
        return None, f"{last}-12-31"
    return f"{year}-01-01", f"{year}-12-31"


MONTHS = {
    name: i + 1
    for i, names in enumerate(
        [
            ("january", "jan"), ("february", "feb"), ("march", "mar"),
            ("april", "apr"), ("may",), ("june", "jun"), ("july", "jul"),
            ("august", "aug"), ("september", "sep", "sept"),
            ("october", "oct"), ("november", "nov"), ("december", "dec"),
        ]
    )
    for name in names
}  # fmt: skip


def month_range(words: str, today: date) -> Optional[Range]:
    """A month or a range of months in English, e.g. "March 2026", "in July
    2025" or "from January to April 2025". With no year, the most recent
    month that has started. "since May" runs to today. Clairic often gives
    a wrong last day, e.g. 2026-03-02 for "March 2026". A day number, or
    "until" or "before" with a month, leaves the range to the model."""
    rest = re.sub(r"(?<!\d)\d{4}(?!\d)", " ", words.lower())
    tokens = re.findall(r"[-–]|[^\W\d_]+|\S", rest)
    months = [MONTHS[t] for t in tokens if t in MONTHS]
    if not months or len(months) > 2:
        return None
    if any(t not in YEAR_WORDS and t not in MONTHS for t in tokens):
        return None
    years = [int(y) for y in re.findall(r"(?<!\d)(\d{4})(?!\d)", words)]
    if len(years) > 1:
        return None
    first, last = months[0], months[-1]
    if re.search(r"\b(until|till|up|through|before|after)\b", rest):
        return None
    if len(months) == 1 and re.search(r"\b(since|from|starting)\b", rest):
        # "since May": from the 1st of that month to today.
        year = years[0] if years else today.year
        if not years and date(year, first, 1) > today:
            year -= 1
        return str(date(year, first, 1)), str(today)
    if years:
        end_year = years[0]
    else:
        end_year = (
            today.year
            if date(today.year, last, 1) <= today
            else today.year - 1
        )
    start_year = end_year - 1 if first > last else end_year
    return str(date(start_year, first, 1)), str(_month_end(end_year, last))


def whole_range(words: str, today: date) -> Optional[Range]:
    """The whole record of the dataset, e.g. "all years" or "all time"."""
    if not re.search(
        r"\b(?:all|every)\s+(?:the\s+)?(?:years|time|dates)\b"
        r"|\b(?:whole|full|entire)\s+(?:record|period|time\s*series|range)\b",
        words,
        re.I,
    ):
        return None
    return None, None


RULES = (
    whole_range,
    year_range,
    month_range,
    season_range,
    quarter_range,
    half_range,
    relative_range,
    recent_range,
)


def calendar_range(words: str, today: date) -> Optional[Range]:
    """The range of the first calendar rule that knows the words, or None
    when the range must come from the dates of the model."""
    for rule in RULES:
        found = rule(words, today)
        if found is not None:
            return found
    return None


# --- The map view and the canopy cover --------------------------------------


def is_map_view(words: str) -> bool:
    """Whether the place words mean the area the map shows now, e.g. "here",
    "this area" or "the map view"."""
    return bool(
        re.fullmatch(
            r"(?:in |on )?(?:here|there|this (?:area|region|place|view)|"
            r"that (?:area|region|place)|the (?:map|map view|current view|"
            r"same area))",
            re.sub(r"[.,!?]+$", "", words.strip()),
            re.I,
        )
    )


AREA_TYPES = re.compile(
    r"\b(?:protected area|key biodiversity area|biodiversity area|"
    r"nature reserve|reserve|region|province|state|district)\s*$",
    re.I,
)


def place_search_names(words: str) -> list[str]:
    """The names to give to `search_aois`, in order: the words of Clairic,
    then a cleaned form when it differs. The cleaned form has no type word
    at the end ("Corona Forestal protected area"), no possessive
    ("Indonesia's"), no text in brackets ("Cordoba (ARG)"), and a comma for
    "in" between two names ("Pocho in Cordoba")."""
    cleaned = re.sub(r"\([^)]*\)", " ", words)
    cleaned = re.sub(r"(?<=\w)['’]s\b", "", cleaned)
    cleaned = re.sub(r"\s+in\s+(?=[A-ZÀ-Ý])", ", ", cleaned)
    cleaned = re.sub(r"^(?:the|in)\s+", "", cleaned.strip(), flags=re.I)
    cleaned = AREA_TYPES.sub("", cleaned).strip(" ,.")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return [words] if not cleaned or cleaned == words else [words, cleaned]


SNAP_NOTE_DISTANCE = 5


def snap_canopy(
    value: float, permitted: list[int]
) -> tuple[int, Optional[str]]:
    """The permitted canopy cover nearest to `value`, and a note when it is
    more than SNAP_NOTE_DISTANCE points from it. On a tie, the higher value."""
    nearest = min(permitted, key=lambda v: (abs(v - value), -v))
    note = None
    if abs(nearest - value) > SNAP_NOTE_DISTANCE:
        note = (
            f"The dataset has no {value:g}% canopy cover threshold. "
            f"Zap uses {nearest}%."
        )
    return nearest, note
