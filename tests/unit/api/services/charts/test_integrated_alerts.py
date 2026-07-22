from src.api.services.charts import column_to_rows
from src.api.services.charts.integrated_alerts import (
    IntegratedAlertsChartGenerator,
)
from tests.unit.api.services.charts.conftest import load_fixture_rows

IA_DATA = {
    "alert_date": ["2024-03-01", "2024-03-20", "2024-04-05", "2024-04-18"],
    "alert_confidence": ["high", "low", "high", "high"],
    "area_ha": [10.0, 5.0, 20.0, 2.5],
    "aoi_id": ["BRA"] * 4,
    "aoi_type": ["admin"] * 4,
}
IA_ROWS = column_to_rows(IA_DATA)


def test_ia_generates_one_wide_line_chart_by_confidence():
    charts = IntegratedAlertsChartGenerator().generate(IA_ROWS)
    assert len(charts) == 1
    fe = charts[0].to_frontend_dict()
    assert fe["type"] == "line"
    assert fe["xAxis"] == "month"
    # Multi-series must ride on series_fields: the frontend widget drops
    # color_field, so long-format data would render as a single scrambled
    # line.
    assert fe["seriesFields"] == ["low", "high"]
    assert fe["yAxis"] == ""
    assert "(ha)" in fe["title"]


def test_ia_aggregates_area_by_month_into_confidence_columns():
    chart = IntegratedAlertsChartGenerator().generate(IA_ROWS)[0]
    by_month = {row["month"]: row for row in chart.chart_data}
    # March: high=10, low=5 (kept separate by confidence)
    assert by_month["2024-03"]["high"] == 10.0
    assert by_month["2024-03"]["low"] == 5.0
    # April: high alerts on two days summed (20 + 2.5); no low alerts → 0
    assert by_month["2024-04"]["high"] == 22.5
    assert by_month["2024-04"]["low"] == 0.0


def test_ia_orders_series_low_high_highest():
    rows = column_to_rows(
        {
            "alert_date": ["2024-01-01", "2024-01-02", "2024-01-03"],
            "alert_confidence": ["highest", "low", "high"],
            "area_ha": [1.0, 2.0, 3.0],
            "aoi_id": ["BRA"] * 3,
            "aoi_type": ["admin"] * 3,
        }
    )
    chart = IntegratedAlertsChartGenerator().generate(rows)[0]
    assert chart.series_fields == ["low", "high", "highest"]


def test_ia_empty_rows_produce_no_charts():
    assert IntegratedAlertsChartGenerator().generate([]) == []


def test_real_response_shape_produces_monthly_series():
    rows = load_fixture_rows("integrated_alerts")
    chart = IntegratedAlertsChartGenerator().generate(rows)[0]
    months = [row["month"] for row in chart.chart_data]
    assert months == sorted(months)
    assert all(len(month) == 7 for month in months)  # YYYY-MM
    assert set(chart.series_fields) <= {"low", "high", "highest"}
