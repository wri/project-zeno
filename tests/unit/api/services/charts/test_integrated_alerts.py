from src.api.services.charts import column_to_rows
from src.api.services.charts.integrated_alerts import (
    IntegratedAlertsChartGenerator,
)

IA_DATA = {
    "alert_date": ["2024-03-01", "2024-03-20", "2024-04-05", "2024-04-18"],
    "alert_confidence": ["high", "low", "high", "high"],
    "area_ha": [10.0, 5.0, 20.0, 2.5],
    "aoi_id": ["BRA"] * 4,
    "aoi_type": ["admin"] * 4,
}
IA_ROWS = column_to_rows(IA_DATA)


def test_ia_generates_one_line_chart_by_confidence():
    chart = IntegratedAlertsChartGenerator().generate(IA_ROWS)[0]
    fe = chart.to_frontend_dict()
    assert fe["type"] == "line"
    assert fe["xAxis"] == "month"
    assert fe["yAxis"] == "area_ha"
    assert fe["colorField"] == "alert_confidence"
    # snake_case persistence parity
    assert chart.to_orm_kwargs()["color_field"] == "alert_confidence"


def test_ia_aggregates_area_by_month_and_confidence():
    chart = IntegratedAlertsChartGenerator().generate(IA_ROWS)[0]
    by_key = {
        (r["month"], r["alert_confidence"]): r["area_ha"]
        for r in chart.chart_data
    }
    # March: high=10, low=5 (kept separate by confidence)
    assert by_key[("2024-03", "high")] == 10.0
    assert by_key[("2024-03", "low")] == 5.0
    # April: high alerts on two days summed (20 + 2.5)
    assert by_key[("2024-04", "high")] == 22.5
