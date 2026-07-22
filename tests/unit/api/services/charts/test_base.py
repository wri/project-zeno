from src.api.services.charts.base import (
    column_to_rows,
    drop_zero_rows,
    monthly_totals,
    sort_rows,
)


def test_column_to_rows_builds_row_dicts():
    rows = column_to_rows({"a": [1, 2], "b": ["x", "y"]})
    assert rows == [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]


def test_column_to_rows_pads_ragged_columns_with_none():
    # The real grasslands response has a shorter aoi_type column; data rows
    # must not be truncated to it.
    rows = column_to_rows({"year": [2000, 2001, 2002], "aoi_type": ["admin"]})
    assert len(rows) == 3
    assert rows[0] == {"year": 2000, "aoi_type": "admin"}
    assert rows[2] == {"year": 2002, "aoi_type": None}


def test_column_to_rows_empty_data():
    assert column_to_rows({}) == []


def test_drop_zero_rows_removes_zero_and_missing():
    rows = [{"v": 1.0}, {"v": 0.0}, {"v": None}, {}]
    assert drop_zero_rows(rows, "v") == [{"v": 1.0}]


def test_sort_rows_orders_by_column():
    rows = [{"y": 2}, {"y": 1}]
    assert sort_rows(rows, "y") == [{"y": 1}, {"y": 2}]


def test_monthly_totals_ungrouped_sums_by_month():
    rows = [
        {"date": "2024-02-03", "v": 1.0},
        {"date": "2024-01-01", "v": 2.0},
        {"date": "2024-01-15", "v": 3.0},
    ]
    assert monthly_totals(rows, "date", "v") == [
        {"month": "2024-01", "v": 5.0},
        {"month": "2024-02", "v": 1.0},
    ]


def test_monthly_totals_grouped_pivots_wide_and_fills_zero():
    rows = [
        {"date": "2024-01-01", "g": "a", "v": 1.0},
        {"date": "2024-01-02", "g": "a", "v": 2.0},
        {"date": "2024-02-01", "g": "b", "v": 4.0},
    ]
    assert monthly_totals(rows, "date", "v", group_column="g") == [
        {"month": "2024-01", "a": 3.0, "b": 0.0},
        {"month": "2024-02", "a": 0.0, "b": 4.0},
    ]
