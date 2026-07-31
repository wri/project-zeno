"""Unit tests for the phase 2 deterministic chart color resolver."""

from src.agent.subagents.analyst.charts.color_resolver import (
    resolve_chart_colors,
)
from src.agent.subagents.analyst.charts.model import InsightChart

# Global land cover (dataset_id=1): categories only, no series/divergent color.
LAND_COVER_ID = 1
# Tree cover loss by dominant driver: categories AND a series_color.
DRIVER_ID = 8
# Tree cover loss: series_color only, no categories.
TREE_COVER_LOSS_ID = 4
# Forest GHG net flux: divergent_colors only, no categories.
GHG_ID = 6


def _pie_chart(rows) -> InsightChart:
    return InsightChart(
        title="Land cover",
        chart_type="pie",
        x_axis="land_cover_type",
        chart_data=rows,
    )


def test_no_dataset_id_yields_no_colors():
    chart = InsightChart(
        title="Loss", chart_type="bar", x_axis="year", y_axis="loss"
    )
    resolved = resolve_chart_colors(chart, None)
    assert resolved.dataset_id is None
    assert resolved.color_map == {}
    assert resolved.series_color is None
    assert resolved.divergent_colors is None


def test_non_categorical_chart_gets_no_color_map_but_keeps_dataset_id():
    chart = InsightChart(
        title="Loss", chart_type="bar", x_axis="year", y_axis="loss"
    )
    resolved = resolve_chart_colors(chart, TREE_COVER_LOSS_ID)
    assert resolved.dataset_id == TREE_COVER_LOSS_ID
    assert resolved.color_map == {}
    assert resolved.series_color == "#DC6C9A"
    assert resolved.divergent_colors is None


def test_pie_chart_resolves_color_map_from_slug_column():
    rows = [
        {
            "land_cover_type": "Bosque",
            "land_cover_type__slug": "tree_cover",
            "value": 10,
        },
        {
            "land_cover_type": "Cultivo",
            "land_cover_type__slug": "cropland",
            "value": 5,
        },
    ]
    resolved = resolve_chart_colors(_pie_chart(rows), LAND_COVER_ID)
    assert resolved.color_map == {
        "tree_cover": "#246E24",
        "cropland": "#fff183",
    }


def test_pie_chart_falls_back_to_raw_column_without_slug_column():
    rows = [{"land_cover_type": "tree_cover", "value": 10}]
    resolved = resolve_chart_colors(_pie_chart(rows), LAND_COVER_ID)
    assert resolved.color_map == {"tree_cover": "#246E24"}


def test_unrecognized_slug_gets_deterministic_fallback_color():
    rows = [
        {
            "land_cover_type": "Agriculture (grouped)",
            "land_cover_type__slug": "agriculture",
            "value": 10,
        }
    ]
    first = resolve_chart_colors(_pie_chart(rows), LAND_COVER_ID)
    second = resolve_chart_colors(_pie_chart(rows), LAND_COVER_ID)
    assert first.color_map["agriculture"] not in {
        None,
        "",
    }
    assert first.color_map["agriculture"].startswith("#")
    # Same slug -> same fallback color across regenerations.
    assert first.color_map["agriculture"] == second.color_map["agriculture"]


def test_color_field_drives_color_map_for_non_pie_charts():
    rows = [
        {"year": 2020, "driver": "Logging", "driver__slug": "logging"},
        {"year": 2021, "driver": "Wildfire", "driver__slug": "wildfire"},
    ]
    chart = InsightChart(
        title="Loss by driver",
        chart_type="bar",
        x_axis="year",
        y_axis="area_ha",
        color_field="driver",
        chart_data=[{**r, "area_ha": 1} for r in rows],
    )
    resolved = resolve_chart_colors(chart, DRIVER_ID)
    assert resolved.color_map == {
        "logging": "#52A44E",
        "wildfire": "#885128",
    }
    # Dataset-level series_color still passes through alongside category colors.
    assert resolved.series_color == "#DC6C9A"


def test_divergent_colors_pass_through():
    chart = InsightChart(
        title="Net flux", chart_type="bar", x_axis="country", y_axis="net_flux"
    )
    resolved = resolve_chart_colors(chart, GHG_ID)
    assert resolved.divergent_colors == {
        "positive": "#9a65c0",
        "negative": "#137375",
    }
    assert resolved.color_map == {}
