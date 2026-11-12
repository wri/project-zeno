"""Tests for the Clairic client of zap mode: the calendar rules, the canopy
snap, the place names and the failures that send the planner to jev."""

from datetime import date

import httpx
import pytest

from src.api.config import APISettings
from src.api.services.zap import extract as x

TODAY = date(2026, 11, 12)


@pytest.mark.parametrize(
    ("words", "expected"),
    [
        # Whole years: Clairic often gives a wrong last day for these.
        ("in 2025", ("2025-01-01", "2025-12-31")),
        ("2022年", ("2022-01-01", "2022-12-31")),
        ("between 2001 and 2024", ("2001-01-01", "2024-12-31")),
        ("2015-2020", ("2015-01-01", "2020-12-31")),
        ("from 2017 to 2022", ("2017-01-01", "2022-12-31")),
        ("since 2015", ("2015-01-01", "2026-11-12")),
        ("after 2015", ("2016-01-01", "2026-11-12")),
        ("until 2010", (None, "2010-12-31")),
        ("before 2010", (None, "2009-12-31")),
        # Months.
        ("March 2026", ("2026-03-01", "2026-03-31")),
        ("only March 2026", ("2026-03-01", "2026-03-31")),
        ("from January to April 2025", ("2025-01-01", "2025-04-30")),
        ("February 2024", ("2024-02-01", "2024-02-29")),
        ("December", ("2025-12-01", "2025-12-31")),
        ("November to February", ("2025-11-01", "2026-02-28")),
        ("since May", ("2026-05-01", "2026-11-12")),
        ("from March 2025", ("2025-03-01", "2026-11-12")),
        # A range of months over two years.
        (
            "between December 2024 and February 2025",
            ("2024-12-01", "2025-02-28"),
        ),
        ("December 2024 to February 2025", ("2024-12-01", "2025-02-28")),
        ("from Nov 2023 to Mar 2024", ("2023-11-01", "2024-03-31")),
        ("June 2022 - May 2024", ("2022-06-01", "2024-05-31")),
        # The calendar month before today, not a part of it.
        ("last month", ("2026-10-01", "2026-10-31")),
        ("the last month", ("2026-10-01", "2026-10-31")),
        ("the previous month", ("2026-10-01", "2026-10-31")),
        ("in the last month", ("2026-10-01", "2026-10-31")),
        # Seasons, quarters and halves.
        ("winter 2024", ("2023-12-01", "2024-02-29")),
        ("last summer", ("2026-06-01", "2026-08-31")),
        ("Q3 2021", ("2021-07-01", "2021-09-30")),
        ("the second quarter of 2022", ("2022-04-01", "2022-06-30")),
        ("Q4", ("2026-10-01", "2026-12-31")),
        ("the second half of 2024", ("2024-07-01", "2024-12-31")),
        # Back from today.
        ("the last 3 months", ("2026-08-12", "2026-11-12")),
        ("past week", ("2026-11-05", "2026-11-12")),
        ("the last two years", ("2024-11-12", "2026-11-12")),
        ("recent", ("2025-11-12", "2026-11-12")),
        # The whole record.
        ("all years", (None, None)),
        ("the full record", (None, None)),
    ],
)
def test_calendar_rules(words, expected):
    assert x.calendar_range(words, TODAY) == expected


@pytest.mark.parametrize(
    "words",
    [
        "15 June 2025",  # a day
        "marzo de 2022",  # not English
        "this year",
        "the past month",  # a period back from today: left to the model
        "February 2025 to December 2024",  # the end is before the start
        "last year",
        "5-year period",
    ],
)
def test_other_words_use_the_model_dates(words):
    assert x.calendar_range(words, TODAY) is None


def test_last_month_in_january_is_december():
    assert x.calendar_range("last month", date(2027, 1, 5)) == (
        "2026-12-01",
        "2026-12-31",
    )


def test_last_month_in_march_ends_on_the_last_day_of_february():
    assert x.calendar_range("last month", date(2024, 3, 31)) == (
        "2024-02-01",
        "2024-02-29",
    )


def test_a_month_range_with_a_year_before_the_months_uses_the_model():
    assert x.month_range("2024 December to February 2025", TODAY) is None


def test_relative_month_keeps_the_month_end():
    assert x.relative_range("last month", date(2026, 3, 31)) is None
    assert x.relative_range("the last 1 month", date(2026, 3, 31)) == (
        "2026-02-28",
        "2026-03-31",
    )


@pytest.mark.parametrize(
    ("value", "expected", "note"),
    [
        (50, 50, False),
        (12, 10, False),
        (40, 50, True),  # a tie: the higher value
        (90, 75, True),
        (3, 10, True),
    ],
)
def test_snap_canopy(value, expected, note):
    snapped, text = x.snap_canopy(value, [10, 15, 20, 25, 30, 50, 75])
    assert snapped == expected
    assert (text is not None) is note


@pytest.mark.parametrize(
    ("words", "map_view"),
    [
        ("here", True),
        ("this area", True),
        ("the map", True),
        ("in this region.", True),
        ("Pará", False),
        ("the map darker", False),
    ],
)
def test_is_map_view(words, map_view):
    assert x.is_map_view(words) is map_view


@pytest.mark.parametrize(
    ("words", "names"),
    [
        ("Sara, Bolivia", ["Sara, Bolivia"]),
        (
            "Corona Forestal protected area",
            ["Corona Forestal protected area", "Corona Forestal"],
        ),
        ("Pocho in Cordoba", ["Pocho in Cordoba", "Pocho, Cordoba"]),
        ("Indonesia's", ["Indonesia's", "Indonesia"]),
        ("Cordoba (ARG)", ["Cordoba (ARG)", "Cordoba"]),
        ("Madre de Dios", ["Madre de Dios"]),
    ],
)
def test_place_search_names(words, names):
    assert x.place_search_names(words) == names


# --- The client -------------------------------------------------------------


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setattr(APISettings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(x, "RETRY_PAUSE_SECONDS", 0)


def _client(*responses):
    """A client that gives the responses in order and records the bodies."""
    queue = list(responses)
    bodies = []

    def handler(request):
        bodies.append(request.read())
        status, body = queue.pop(0)
        return httpx.Response(status, json=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), bodies


def _answer(value, p_null=0.01):
    return {"value": value, "guess": value, "p_null": p_null}


async def test_extract_fields_sends_the_reference_date(key):
    client, bodies = _client(
        (200, {"answers": {"when": _answer("2019"), "start": _answer(None)}})
    )
    answers = await x.extract_fields(
        "state",
        {"when": {"type": "text"}, "start": {"type": "date"}},
        reference_date=TODAY,
        client=client,
    )
    assert answers["when"]["value"] == "2019"
    assert b'"reference_date":"2026-11-12"' in bodies[0].replace(b" ", b"")
    assert b'"model":"cloudflare/clairic"' in bodies[0].replace(b" ", b"")


async def test_extract_fields_tries_again_after_a_capacity_error(key):
    client, bodies = _client(
        (429, {"error": {"message": "Capacity temporarily exceeded"}}),
        (200, {"answers": {"place": _answer("Pará")}}),
    )
    answers = await x.extract_fields(
        "p", {"place": {"type": "text"}}, client=client
    )
    assert answers["place"]["value"] == "Pará"
    assert len(bodies) == 2


async def test_extract_fields_fails_after_the_retry(key):
    client, bodies = _client((503, {}), (503, {}))
    with pytest.raises(x.ExtractError):
        await x.extract_fields("p", {"place": {"type": "text"}}, client=client)
    assert len(bodies) == 2


async def test_extract_fields_fails_on_a_missing_answer(key):
    client, _ = _client((200, {"answers": {"place": _answer("Pará")}}))
    with pytest.raises(x.ExtractError):
        await x.extract_fields(
            "p",
            {"place": {"type": "text"}, "canopy": {"type": "number"}},
            client=client,
        )


async def test_extract_fields_needs_the_key(monkeypatch):
    monkeypatch.setattr(APISettings, "openrouter_api_key", "")
    with pytest.raises(x.ExtractError):
        await x.extract_fields("p", {"place": {"type": "text"}})


async def test_extract_fields_fails_on_a_network_error(key):
    def handler(request):
        raise httpx.ConnectTimeout("slow")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(x.ExtractError):
        await x.extract_fields("p", {"place": {"type": "text"}}, client=client)


# --- The calls --------------------------------------------------------------


@pytest.fixture
def answers(monkeypatch):
    """Give `extract_fields` fixed answers; record the states."""
    states = []

    def install(values):
        async def fake(state, fields, reference_date=None, client=None):
            states.append(state)
            return {name: values[name] for name in fields}

        monkeypatch.setattr(x, "extract_fields", fake)
        return states

    return install


async def test_time_from_a_calendar_rule(answers):
    states = answers(
        {
            "when": _answer("in 2025"),
            "start": _answer("2025-01-01"),
            "end": _answer("2026-12-12"),  # a wrong end, as Clairic gives
        }
    )
    time = await x.extract_time("Loss in Colombia in 2025", TODAY)
    assert time.range == ("2025-01-01", "2025-12-31")
    assert time.source == "code"
    # Call B reads the app context and today's date.
    assert "Today is 2026-11-12." in states[0]
    assert "on a map" in states[0]


async def test_time_from_the_model_dates(answers):
    answers(
        {
            "when": _answer("15 June 2025"),
            "start": _answer("2025-06-15"),
            "end": _answer("2025-06-15"),
        }
    )
    time = await x.extract_time("Alerts on 15 June 2025", TODAY)
    assert time.range == ("2025-06-15", "2025-06-15")
    assert time.source == "clairic"


async def test_no_when_is_no_time_also_with_dates(answers):
    answers(
        {
            "when": _answer(None, p_null=1.0),
            "start": _answer("2026-11-01"),
            "end": _answer("2026-11-12"),
        }
    )
    time = await x.extract_time("Loss in Brazil", TODAY)
    assert time.range is None


async def test_today_alone_is_no_time(answers):
    answers(
        {
            "when": _answer("today"),
            "start": _answer("2026-11-12"),
            "end": _answer("2026-11-12"),
        }
    )
    assert (await x.extract_time("weather today?", TODAY)).range is None


async def test_no_end_runs_to_today(answers):
    answers(
        {
            "when": _answer("since May"),
            "start": _answer("2026-05-01"),
            "end": _answer(None, p_null=0.9),
        }
    )
    time = await x.extract_time("alerts since May", TODAY)
    assert time.range == ("2026-05-01", "2026-11-12")


async def test_no_start_is_a_failure(answers):
    answers(
        {
            "when": _answer("the dry season"),
            "start": _answer(None, p_null=0.9),
            "end": _answer("2026-09-30"),
        }
    )
    with pytest.raises(x.ExtractError):
        await x.extract_time("alerts in the dry season", TODAY)


async def test_place_reads_the_request_only(answers):
    states = answers(
        {"place": _answer("Ghana"), "canopy": _answer(50, p_null=0.02)}
    )
    place = await x.extract_place("Loss in Ghana at 50% canopy")
    assert states == ["Loss in Ghana at 50% canopy"]
    assert place.place == "Ghana"
    assert place.canopy == 50
    assert place.canopy_probability == 0.98


async def test_place_drops_a_canopy_out_of_range(answers):
    answers({"place": _answer(None, p_null=0.95), "canopy": _answer(250)})
    place = await x.extract_place("thanks")
    assert place.place is None
    assert place.canopy is None


async def test_extract_gives_the_error_of_a_failed_call(answers, monkeypatch):
    answers({"place": _answer("Pará"), "canopy": _answer(None, p_null=1.0)})

    async def fail(prompt, today):
        raise x.ExtractError("no answer")

    monkeypatch.setattr(x, "extract_time", fail)
    place, time = await x.extract("Pará", TODAY)
    assert isinstance(place, x.PlaceExtraction)
    assert isinstance(time, x.ExtractError)


async def test_dashboard_numbers_have_no_place(answers):
    states = answers(
        {
            "canopy": _answer(None, p_null=0.97),
            "cloud": _answer(10, p_null=0.05),
        }
    )
    numbers = await x.extract_numbers("imagery with under 10% clouds")
    assert states == ["imagery with under 10% clouds"]
    assert set(x.CALL_A_DASHBOARD) == {"canopy", "cloud"}
    assert numbers.canopy is None
    assert numbers.cloud == 10
    assert numbers.cloud_probability == 0.95


async def test_extract_dashboard_gives_the_error_of_a_failed_call(
    answers, monkeypatch
):
    answers({"canopy": _answer(None), "cloud": _answer(None)})

    async def fail(prompt, today):
        raise x.ExtractError("no answer")

    monkeypatch.setattr(x, "extract_time", fail)
    numbers, time = await x.extract_dashboard("add a map", TODAY)
    assert isinstance(numbers, x.NumberExtraction)
    assert isinstance(time, x.ExtractError)
