"""Tests for the code gate of a curated chart in the agent."""

from src.agent.datasets.handlers.analytics_handler import (
    GRASSLANDS_ID,
    LAND_GHG_INVENTORY_ID,
    TREE_COVER_ID,
    TREE_COVER_LOSS_ID,
)
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.gate import (
    charts_with_data,
    count_areas,
    has_data,
    view_gate,
)
from src.api.services.charts.views import VIEWS, agent_views, get_view


def _chart(view_id, rows, y_axis="area_ha", position=3):
    return InsightChart(
        position=position,
        title=view_id or "generated",
        chart_type="bar",
        x_axis="year",
        y_axis=y_axis,
        chart_data=rows,
        view_id=view_id,
    )


def test_only_tree_cover_loss_is_enabled():
    assert {v.id for v in VIEWS if v.agent_enabled} == {
        "tcl.annual_loss",
        "tcl.annual_emissions",
    }
    assert [v.id for v in agent_views(TREE_COVER_LOSS_ID)] == [
        "tcl.annual_loss",
        "tcl.annual_emissions",
    ]
    assert agent_views(GRASSLANDS_ID) == []
    # LGMS keeps its curated-only path.
    assert agent_views(LAND_GHG_INVENTORY_ID) == []


def test_count_areas():
    rows = [{"aoi_id": "A"}, {"aoi_id": "A"}, {"aoi_id": "B"}]
    assert count_areas(rows, default=9) == 2
    assert count_areas([{"name": "Pará"}], default=9) == 1
    assert count_areas([{"year": 2020}], default=1) == 1
    assert count_areas([], default=0) == 0


def test_view_gate_one_area():
    gate = view_gate(TREE_COVER_LOSS_ID, 1)

    assert gate.passed
    assert gate.title_keys == [
        "charts.tcl.annual_loss",
        "charts.tcl.annual_emissions",
    ]


def test_view_gate_several_areas_fail_a_one_area_view():
    gate = view_gate(TREE_COVER_LOSS_ID, 3)

    assert not gate.passed
    assert "3 areas" in gate.reason


def test_view_gate_fails_without_an_enabled_view():
    assert not view_gate(GRASSLANDS_ID, 1).passed
    assert not view_gate(None, 1).passed
    # tree_cover.extent is many_areas but not enabled.
    assert get_view("tree_cover.extent").shape == "many_areas"
    assert not view_gate(TREE_COVER_ID, 3).passed


def test_has_data():
    assert has_data(_chart("tcl.annual_loss", [{"area_ha": 0}]))
    assert not has_data(_chart("tcl.annual_loss", [{"area_ha": None}]))
    assert not has_data(_chart("tcl.annual_loss", []))


def test_charts_with_data_leaves_out_empty_and_unknown_charts():
    loss = _chart("tcl.annual_loss", [{"year": 2021, "area_ha": 5.0}])
    emissions = _chart(
        "tcl.annual_emissions",
        [{"year": 2021, "carbon_emissions_MgCO2e": None}],
        y_axis="carbon_emissions_MgCO2e",
    )
    not_enabled = _chart("grasslands.by_year", [{"area_ha": 1.0}])
    generated = _chart(None, [{"area_ha": 1.0}])

    kept = charts_with_data([emissions, not_enabled, generated, loss])

    assert kept == [loss]
    assert loss.position == 0
