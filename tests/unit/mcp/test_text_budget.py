"""How much of a pull's rows the tool text shows: CSV when the rows are few
and short enough, per-column stats otherwise, numbers rounded."""

import pytest

import src.mcp.data as data
from src.mcp.data import (
    MAX_TEXT_ROWS,
    TEXT_CHAR_BUDGET,
    rows_text,
    text_csv,
    text_number,
)


@pytest.mark.parametrize(
    "value, shown",
    [
        (463591.15581773105, 463591.16),
        (-4020198198.8015447, -4020198198.8),
        (0.000123456, 0.0001235),
        (2021, 2021),
        ("Pará", "Pará"),
        (None, None),
    ],
)
def test_text_numbers_are_rounded(value, shown):
    assert text_number(value) == shown


def _rows(n, name="Pará"):
    return [
        {
            "aoi_id": "BRA.14",
            "aoi_type": "admin",
            "year": 2000 + i,
            "area_ha": 463591.15581773105,
            "name": name,
        }
        for i in range(n)
    ]


async def test_few_short_rows_are_shown_as_csv():
    text = await rows_text(_rows(3), 4)
    assert text == text_csv(_rows(3))
    assert text.splitlines()[:2] == [
        "year,area_ha,name",
        "2000,463591.16,Pará",
    ]


async def test_too_many_rows_are_summarised():
    text = await rows_text(_rows(MAX_TEXT_ROWS + 1), 4)
    assert "year,area_ha" not in text
    assert f"These {MAX_TEXT_ROWS + 1} rows are too large to show here" in text


async def test_rows_too_wide_for_the_budget_are_summarised():
    # Few rows, but long area names: the CSV is over the budget.
    rows = _rows(40, name="x" * (TEXT_CHAR_BUDGET // 40))
    assert len(text_csv(rows)) > TEXT_CHAR_BUDGET
    text = await rows_text(rows, 4)
    assert "too large to show here" in text
    assert len(text) < TEXT_CHAR_BUDGET


async def test_the_budget_is_what_is_left(monkeypatch):
    rows = _rows(3)
    assert await rows_text(rows, 4, budget=len(text_csv(rows))) == text_csv(
        rows
    )
    assert "too large" in await rows_text(
        rows, 4, budget=len(text_csv(rows)) - 1
    )


async def test_curated_only_rows_are_withheld(monkeypatch):
    monkeypatch.setattr(data, "is_curated_only", lambda dataset_id: True)
    assert await rows_text(_rows(3), 4) == data.CURATED_ONLY_DATA_WITHHELD


def test_the_heading_names_the_first_areas_and_counts_the_rest():
    pull = data.Pull(
        ds={"dataset_name": "Tree cover loss"},
        areas=[{"name": f"District {i}"} for i in range(700)],
        start_date="2020-01-01",
        end_date="2021-12-31",
        clamped=False,
        context_layer=None,
        canopy_cover=None,
        rows=[],
        source_url=None,
        request=None,
        metadata=None,
        retrieved_at="2026-10-22T00:00:00Z",
        rows_sha256="",
    )
    heading = pull.heading()
    assert "District 9;" not in heading
    assert "District 9 and 690 more" in heading
    assert "District 10" not in heading


async def test_the_text_says_where_the_rows_are():
    text = await rows_text(_rows(MAX_TEXT_ROWS + 1), 4)
    assert "The structured result and pull.py hold all of them." in text

    text = await rows_text(_rows(data.MAX_ROWS + 1), 4)
    assert f"holds the first {data.MAX_ROWS}; pull.py writes all" in text
