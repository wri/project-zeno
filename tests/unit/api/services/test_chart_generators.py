from src.agent.datasets.handlers.analytics_handler import (
    INTEGRATED_ALERTS_ID,
    LAND_GHG_INVENTORY_ID,
    TREE_COVER_LOSS_ID,
)
from src.api.services.charts import (
    DETERMINISTIC_GENERATORS,
    IntegratedAlertsChartGenerator,
    LGMSChartGenerator,
    TCLChartGenerator,
    column_to_rows,
)

TCL_DATA = {
    "tree_cover_loss_year": [2020, 2021, 2022],
    "area_ha": [1000.0, 0.0, 3000.0],
    "carbon_emissions_MgCO2e": [500.0, 0.0, 1500.0],
    "aoi_id": ["BRA"] * 3,
    "aoi_type": ["admin"] * 3,
}
TCL_ROWS = column_to_rows(TCL_DATA)


def test_can_handle_tcl_dataset():
    assert TCLChartGenerator(TREE_COVER_LOSS_ID).can_handle(TREE_COVER_LOSS_ID)


def test_cannot_handle_other_dataset():
    assert not TCLChartGenerator(TREE_COVER_LOSS_ID).can_handle(1)


def test_tcl_generator_registered():
    assert any(
        isinstance(gen, TCLChartGenerator) for gen in DETERMINISTIC_GENERATORS
    )


def test_generates_two_charts():
    charts = TCLChartGenerator(TREE_COVER_LOSS_ID).generate(TCL_ROWS)
    assert len(charts) == 2


def test_loss_chart_is_bar_with_correct_axes():
    chart = TCLChartGenerator(TREE_COVER_LOSS_ID).generate(TCL_ROWS)[0]
    fe = chart.to_frontend_dict()
    assert fe["type"] == "bar"
    assert fe["xAxis"] == "tree_cover_loss_year"
    assert fe["yAxis"] == "area_ha"
    # snake_case persistence parity
    assert chart.to_orm_kwargs()["chart_type"] == "bar"
    assert chart.to_orm_kwargs()["y_axis"] == "area_ha"


def test_emissions_chart_is_separate_bar_with_correct_axes():
    chart = TCLChartGenerator(TREE_COVER_LOSS_ID).generate(TCL_ROWS)[1]
    fe = chart.to_frontend_dict()
    assert fe["type"] == "bar"
    assert fe["xAxis"] == "tree_cover_loss_year"
    assert fe["yAxis"] == "carbon_emissions_MgCO2e"


def test_drops_rows_where_area_ha_is_zero():
    charts = TCLChartGenerator(TREE_COVER_LOSS_ID).generate(TCL_ROWS)
    for chart in charts:
        for row in chart.chart_data:
            assert row["area_ha"] != 0


def test_sorts_rows_by_year():
    # The analytics API returns rows in arbitrary order (e.g. 2004 first,
    # 2023 last); the chart must come out year-ascending or the frontend's
    # category x-axis renders the years shuffled.
    scrambled = column_to_rows(
        {
            "tree_cover_loss_year": [2004, 2021, 2001, 2023, 2010],
            "area_ha": [100.0, 200.0, 300.0, 400.0, 500.0],
            "carbon_emissions_MgCO2e": [50.0, 100.0, 150.0, 200.0, 250.0],
            "aoi_id": ["BRA"] * 5,
            "aoi_type": ["admin"] * 5,
        }
    )
    charts = TCLChartGenerator(TREE_COVER_LOSS_ID).generate(scrambled)
    for chart in charts:
        years = [row["tree_cover_loss_year"] for row in chart.chart_data]
        assert years == [2001, 2004, 2010, 2021, 2023]


# --- Integrated Alerts -------------------------------------------------------
IA_DATA = {
    "alert_date": ["2024-03-01", "2024-03-20", "2024-04-05", "2024-04-18"],
    "alert_confidence": ["high", "low", "high", "high"],
    "area_ha": [10.0, 5.0, 20.0, 2.5],
    "aoi_id": ["BRA"] * 4,
    "aoi_type": ["admin"] * 4,
}
IA_ROWS = column_to_rows(IA_DATA)


def test_can_handle_integrated_alerts_dataset():
    gen = IntegratedAlertsChartGenerator(INTEGRATED_ALERTS_ID)
    assert gen.can_handle(INTEGRATED_ALERTS_ID)
    assert not gen.can_handle(TREE_COVER_LOSS_ID)


def test_integrated_alerts_generator_registered():
    assert any(
        isinstance(gen, IntegratedAlertsChartGenerator)
        for gen in DETERMINISTIC_GENERATORS
    )


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


# --- LGMS ---------------------------------------------------------------
# Mirrors the merge_lgms_sections() output shape confirmed by
# tests/tools/test_analytics_handler.py::
# test_merge_lgms_sections_flattens_to_category_class_table — notably that a
# vegetation class (tree_gain) carries a non-null value for BOTH
# gross_emissions_MgCO2e and gross_removals_MgCO2 on the same row.
LGMS_DATA = {
    "aoi_id": ["BRA.25"] * 6,
    "aoi_type": ["admin"] * 6,
    "category": [
        "vegetation",
        "vegetation",
        "soil",
        "soil",
        "agriculture",
        "agriculture",
    ],
    "class": [
        "tree_loss",
        "tree_gain",
        "mineral_soil",
        "organic_soil",
        "cropland",
        "livestock",
    ],
    "year": [2016] * 6,
    "gross_emissions_MgCO2e": [10.0, 0.0, 5.0, 3.0, 33.0, 5.0],
    "gross_removals_MgCO2": [-1.0, -2.0, -1.0, None, None, None],
    "net_flux_MgCO2e": [9.0, -2.0, 4.0, 3.0, 33.0, 5.0],
    "area_ha": [100.0, 50.0, 200.0, 7.0, None, None],
}
LGMS_ROWS = column_to_rows(LGMS_DATA)


def test_can_handle_lgms_dataset():
    gen = LGMSChartGenerator(LAND_GHG_INVENTORY_ID)
    assert gen.can_handle(LAND_GHG_INVENTORY_ID)
    assert not gen.can_handle(TREE_COVER_LOSS_ID)


def test_lgms_generator_registered():
    assert any(
        isinstance(gen, LGMSChartGenerator) for gen in DETERMINISTIC_GENERATORS
    )


def test_lgms_generates_three_charts():
    charts = LGMSChartGenerator(LAND_GHG_INVENTORY_ID).generate(LGMS_ROWS)
    assert len(charts) == 3


def test_lgms_charts_are_stacked_bar_with_line_on_year():
    charts = LGMSChartGenerator(LAND_GHG_INVENTORY_ID).generate(LGMS_ROWS)
    for chart in charts:
        fe = chart.to_frontend_dict()
        assert fe["type"] == "stacked-bar-with-line"
        assert fe["xAxis"] == "year"


def test_lgms_full_detail_keeps_both_emissions_and_removals_per_class():
    # tree_gain has emissions=0.0 (still a real, present value) AND
    # removals=-2.0 on the same row — both must survive as distinct series,
    # not collapse into a single "whichever metric is populated" value.
    chart = LGMSChartGenerator(LAND_GHG_INVENTORY_ID).generate(LGMS_ROWS)[0]
    row = chart.chart_data[0]
    assert row["tree_loss_emissions"] == 10.0
    assert row["tree_loss_removals"] == -1.0
    assert row["tree_gain_emissions"] == 0.0
    assert row["tree_gain_removals"] == -2.0
    assert "tree_loss_emissions" in chart.series_fields
    assert "tree_gain_removals" in chart.series_fields


def test_lgms_full_detail_omits_series_for_classes_with_no_such_metric():
    # organic soil has no removals at all (None) — no "organic_soil_removals"
    # series should be fabricated.
    chart = LGMSChartGenerator(LAND_GHG_INVENTORY_ID).generate(LGMS_ROWS)[0]
    row = chart.chart_data[0]
    assert "organic_soil_removals" not in row
    assert "organic_soil_removals" not in chart.series_fields
    assert row["organic_soil_emissions"] == 3.0


def test_lgms_categories_chart_folds_class_into_category():
    chart = LGMSChartGenerator(LAND_GHG_INVENTORY_ID).generate(LGMS_ROWS)[1]
    row = chart.chart_data[0]
    # vegetation_emissions = tree_loss(10.0) + tree_gain(0.0)
    assert row["vegetation_emissions"] == 10.0
    # vegetation_removals = tree_loss(-1.0) + tree_gain(-2.0)
    assert row["vegetation_removals"] == -3.0
    # soil_emissions = mineral_soil(5.0) + organic_soil(3.0)
    assert row["soil_emissions"] == 8.0
    # soil_removals = mineral_soil(-1.0); organic_soil has none
    assert row["soil_removals"] == -1.0
    assert row["cropland_emissions"] == 33.0
    assert row["livestock_emissions"] == 5.0


def test_lgms_summary_chart_folds_categories_further():
    chart = LGMSChartGenerator(LAND_GHG_INVENTORY_ID).generate(LGMS_ROWS)[2]
    row = chart.chart_data[0]
    # land_use_emissions = vegetation_emissions(10.0) + soil_emissions(8.0)
    assert row["land_use_emissions"] == 18.0
    # agriculture_emissions = cropland(33.0) + livestock(5.0)
    assert row["agriculture_emissions"] == 38.0
    # land_use_removals = vegetation_removals(-3.0) + soil_removals(-1.0)
    assert row["land_use_removals"] == -4.0


def test_lgms_groups_rows_by_year_and_sorts_ascending():
    scrambled = column_to_rows(
        {
            "category": ["vegetation", "vegetation", "vegetation", "vegetation"],
            "class": ["tree_loss", "tree_loss", "tree_loss", "tree_loss"],
            "year": [2018, 2016, 2017, 2016],
            "gross_emissions_MgCO2e": [30.0, 10.0, 20.0, 5.0],
            "gross_removals_MgCO2": [None, None, None, None],
        }
    )
    chart = LGMSChartGenerator(LAND_GHG_INVENTORY_ID).generate(scrambled)[0]
    years = [row["year"] for row in chart.chart_data]
    assert years == [2016, 2017, 2018]
    # Both 2016 rows summed: 10.0 + 5.0
    assert chart.chart_data[0]["tree_loss_emissions"] == 15.0


# --- Real-world shape regression -----------------------------------------
# Adapted from an actual recorded /v0/land_change/land_ghg_inventory/analytics
# response (São Tomé and Príncipe, admin/STP, 2016-2024), merged through
# merge_lgms_sections(). This is what first revealed that vegetation
# land_state_class values are "tree_gain"/"tree_loss"/"trees_remaining_trees"
# (not the "trees_remaining"/"non_trees" names LGMS_FULL_SERIES_CLASS_ORDER
# initially guessed), and confirmed a class row can carry a real (non-null,
# even if 0.0) value for BOTH metrics — e.g. this sample's tree_loss row has
# gross_removals_MgCO2=0.0 (not None), which must still be treated as present.
STP_2020_ROWS = column_to_rows(
    {
        "category": [
            "vegetation",
            "vegetation",
            "vegetation",
            "soil",
            "agriculture",
            "agriculture",
        ],
        "class": [
            "tree_gain",
            "tree_loss",
            "trees_remaining_trees",
            "mineral_soil",
            "cropland",
            "livestock",
        ],
        "year": [2020] * 6,
        "gross_emissions_MgCO2e": [0.0, 3259.55, 389.99, 0.0, 1746.69, 12441.84],
        "gross_removals_MgCO2": [-52.27, 0.0, -1351644.73, 0.0, None, None],
    }
)


def test_lgms_real_sample_full_detail_keeps_zero_valued_present_metrics():
    chart = LGMSChartGenerator(LAND_GHG_INVENTORY_ID).generate(STP_2020_ROWS)[0]
    row = chart.chart_data[0]
    # tree_loss's removals is 0.0, not None — a present value, must survive.
    assert row["tree_loss_removals"] == 0.0
    # tree_gain's emissions is 0.0, not None — same requirement in reverse.
    assert row["tree_gain_emissions"] == 0.0
    # trees_remaining_trees carries both a real emissions and removals value.
    assert row["trees_remaining_trees_emissions"] == 389.99
    assert row["trees_remaining_trees_removals"] == -1351644.73


def test_lgms_real_sample_categories_sum_matches_full_detail():
    charts = LGMSChartGenerator(LAND_GHG_INVENTORY_ID).generate(STP_2020_ROWS)
    full_row = charts[0].chart_data[0]
    category_row = charts[1].chart_data[0]
    vegetation_emissions_fields = [
        k for k in full_row if k.endswith("_emissions") and k not in (
            "mineral_soil_emissions", "cropland_emissions", "livestock_emissions"
        )
    ]
    assert category_row["vegetation_emissions"] == sum(
        full_row[k] for k in vegetation_emissions_fields
    )
