from src.api.services.charts import column_to_rows
from src.api.services.charts.dist_alerts import DistAlertsChartGenerator
from tests.unit.api.services.charts.conftest import load_fixture_rows

ROWS = column_to_rows(
    {
        "dist_alert_date": [
            "2024-02-03",
            "2024-01-05",
            "2024-01-20",
            "2024-01-20",
        ],
        "dist_alert_confidence": ["high", "low", "high", "low"],
        "area_ha": [4.0, 1.0, 2.0, 3.0],
        "aoi_id": ["CRI"] * 4,
        "aoi_type": ["admin"] * 4,
    }
)


def test_single_monthly_trend_line():
    charts = DistAlertsChartGenerator().generate(ROWS)
    assert len(charts) == 1
    fe = charts[0].to_frontend_dict()
    assert fe["type"] == "line"
    assert fe["xAxis"] == "month"
    assert fe["yAxis"] == "area_ha"
    assert "(ha)" in fe["title"]


def test_daily_rows_summed_per_month_across_confidences():
    chart = DistAlertsChartGenerator().generate(ROWS)[0]
    assert chart.chart_data == [
        {"month": "2024-01", "area_ha": 6.0},
        {"month": "2024-02", "area_ha": 4.0},
    ]


def test_real_response_shape_produces_monthly_series():
    rows = load_fixture_rows("dist_alerts")
    chart = DistAlertsChartGenerator().generate(rows)[0]
    months = [row["month"] for row in chart.chart_data]
    assert months == sorted(months)
    assert all(len(month) == 7 for month in months)  # YYYY-MM
    assert all(row["area_ha"] > 0 for row in chart.chart_data)
