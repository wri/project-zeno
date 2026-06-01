from src.agent.tools.pick_land_change_dataset import (
    Cause,
    ChangeType,
    Ecosystem,
    MeasurementType,
    Temporal,
    pick_land_change_dataset,
    score_datasets,
)

# ---------------------------------------------------------------------------
# Unit tests for score_datasets() — no I/O, fast
# ---------------------------------------------------------------------------


def test_score_returns_all_datasets():
    results = score_datasets(Ecosystem.forest, None, None, None, None)
    assert len(results) == 10


def test_score_sorted_descending():
    results = score_datasets(
        Ecosystem.forest, ChangeType.loss, None, None, None
    )
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_score_forest_loss_no_cause_favors_tcl_over_driver():
    results = score_datasets(
        Ecosystem.forest, ChangeType.loss, None, None, None
    )
    by_id = {r.dataset_id: r for r in results}
    assert by_id[4].score > by_id[8].score


def test_score_forest_loss_with_cause_favors_driver_over_tcl():
    results = score_datasets(
        Ecosystem.forest, ChangeType.loss, Cause.wildfire, None, None
    )
    by_id = {r.dataset_id: r for r in results}
    assert by_id[8].score > by_id[4].score


def test_score_carbon_strongly_favors_ghg_flux():
    results = score_datasets(
        Ecosystem.forest, None, None, MeasurementType.carbon_emissions, None
    )
    by_id = {r.dataset_id: r for r in results}
    assert by_id[6].score > by_id[4].score


def test_score_net_flux_uniquely_favors_ghg_flux():
    # forest + net_carbon_flux = 2 criteria, max = 4
    results = score_datasets(
        Ecosystem.forest, None, None, MeasurementType.net_carbon_flux, None
    )
    top = results[0]
    assert top.dataset_id == 6
    # All others below max (4)
    others = [r for r in results if r.dataset_id != 6]
    assert all(r.score < 4 for r in others)


def test_score_annual_temporal_penalizes_aggregate_datasets():
    results = score_datasets(
        Ecosystem.forest, ChangeType.loss, None, None, Temporal.annual
    )
    by_id = {r.dataset_id: r for r in results}
    # TCL supports annual; TCL by Driver is aggregate-only → scores lower
    assert by_id[4].score > by_id[8].score


def test_score_wetland_loss_all_below_max():
    # 2 criteria → max = 4; no dataset perfectly matches wetland loss
    results = score_datasets(
        Ecosystem.wetland, ChangeType.loss, None, None, None
    )
    assert all(r.score < 4 for r in results)


def test_score_grassland_gain_all_below_max():
    # 2 criteria → max = 4; no dataset perfectly matches grassland gain
    results = score_datasets(
        Ecosystem.grassland, ChangeType.gain, None, None, None
    )
    assert all(r.score < 4 for r in results)


def test_score_buildup_favors_global_land_cover():
    results = score_datasets(Ecosystem.built_up, None, None, None, None)
    top = results[0]
    assert top.dataset_id == 1


def test_score_dates_within_range_gives_2():
    # TCL covers 2001-2025; requesting 2010-2020 → date_score = 2
    results = score_datasets(
        Ecosystem.forest,
        ChangeType.loss,
        None,
        None,
        None,
        start_date="2010-01-01",
        end_date="2020-12-31",
    )
    by_id = {r.dataset_id: r for r in results}
    # TCL: eco=2, chg=2, dates=2 = 6; without dates it was 4
    assert by_id[4].score == 6


def test_score_dates_outside_range_gives_0_or_1():
    # DIST-ALERT starts 2023-12-01; requesting 2010-2015 → no overlap → 0
    results = score_datasets(
        Ecosystem.all,
        ChangeType.disturbance,
        None,
        None,
        None,
        start_date="2010-01-01",
        end_date="2015-12-31",
    )
    by_id = {r.dataset_id: r for r in results}
    # DIST-ALERT: eco=2, chg=2, dates=0 = 4 (not max=6)
    assert by_id[0].score == 4


def test_score_dates_partial_overlap_gives_1():
    # GLC covers 2015-2024; requesting 2010-2020 → partial overlap → 1
    results = score_datasets(
        Ecosystem.built_up,
        ChangeType.change,
        None,
        None,
        None,
        start_date="2010-01-01",
        end_date="2020-12-31",
    )
    by_id = {r.dataset_id: r for r in results}
    # GLC: eco=2, chg=2, dates=1 = 5 (not max=6)
    assert by_id[1].score == 5


def test_score_tree_cover_gain_checkpoint_dates_give_2():
    # 2000-2020 aligns with valid 5-year checkpoints → date_score = 2
    results = score_datasets(
        Ecosystem.forest,
        ChangeType.gain,
        None,
        None,
        None,
        start_date="2000-01-01",
        end_date="2020-12-31",
    )
    by_id = {r.dataset_id: r for r in results}
    # TreeCoverGain: eco=2, gain=2, dates=2 = 6
    assert by_id[5].score == 6


def test_score_tree_cover_gain_non_checkpoint_dates_give_1():
    # 2012-2018 doesn't align with any 5-year checkpoint → date_score = 1
    results = score_datasets(
        Ecosystem.forest,
        ChangeType.gain,
        None,
        None,
        None,
        start_date="2012-01-01",
        end_date="2018-12-31",
    )
    by_id = {r.dataset_id: r for r in results}
    # TreeCoverGain: eco=2, gain=2, dates=1 = 5 (not max=6)
    assert by_id[5].score == 5


# ---------------------------------------------------------------------------
# Integration tests — selected path (dataset chosen)
# ---------------------------------------------------------------------------


async def test_forest_loss_annual_no_cause_returns_tcl():
    # "How much tree cover loss in Brazil in 2024?"
    result = await pick_land_change_dataset.coroutine(
        state={},
        tool_call_id="test-id",
        change_type=ChangeType.loss,
        ecosystem=Ecosystem.forest,
        temporal=Temporal.annual,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 4
    assert ds["context_layer"] is None


async def test_primary_forest_loss_returns_tcl_primary_forest():
    # "How much primary forest was lost in DRC since 2001?"
    result = await pick_land_change_dataset.coroutine(
        state={},
        tool_call_id="test-id",
        change_type=ChangeType.loss,
        ecosystem=Ecosystem.primary_forest,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 4
    assert ds["context_layer"] == "primary_forest"


async def test_forest_loss_with_wildfire_cause_returns_tcl_by_driver():
    # "Which US state lost the most forest due to wildfires?"
    result = await pick_land_change_dataset.coroutine(
        state={},
        tool_call_id="test-id",
        change_type=ChangeType.loss,
        ecosystem=Ecosystem.forest,
        cause=Cause.wildfire,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 8
    assert ds["context_layer"] == "driver"


async def test_carbon_emissions_forest_returns_ghg_flux():
    # "How much carbon was emitted due to tree cover loss in Indonesia?"
    result = await pick_land_change_dataset.coroutine(
        state={},
        tool_call_id="test-id",
        ecosystem=Ecosystem.forest,
        measurement_type=MeasurementType.carbon_emissions,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 6
    assert ds["context_layer"] is None


async def test_forest_gain_with_dates_returns_tree_cover_gain():
    # "How much tree cover was gained between 2000 and 2020 in the Amazon?"
    result = await pick_land_change_dataset.coroutine(
        state={},
        tool_call_id="test-id",
        change_type=ChangeType.gain,
        ecosystem=Ecosystem.forest,
        start_date="2000-01-01",
        end_date="2020-12-31",
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 5
    assert ds["context_layer"] is None


async def test_land_cover_change_cropland_returns_global_land_cover():
    # "How much land changed to cropland in California in the past decade?"
    result = await pick_land_change_dataset.coroutine(
        state={},
        tool_call_id="test-id",
        change_type=ChangeType.change,
        ecosystem=Ecosystem.cropland,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 1
    assert ds["context_layer"] is None


async def test_grassland_change_returns_grassland_dataset_not_global_land_cover():
    # "Did natural grasslands increase from 2017 to 2022 in Hwange national park?"
    result = await pick_land_change_dataset.coroutine(
        state={},
        tool_call_id="test-id",
        change_type=ChangeType.change,
        ecosystem=Ecosystem.grassland,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 2
    assert ds["context_layer"] is None


async def test_natural_land_snapshot_returns_sbtn():
    # "What percentage of land in Kurtjar People territory is non-natural?"
    result = await pick_land_change_dataset.coroutine(
        state={},
        tool_call_id="test-id",
        ecosystem=Ecosystem.natural_land,
        temporal=Temporal.snapshot,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 3
    assert ds["context_layer"] is None


async def test_grasslands_area_returns_grassland_dataset():
    # "How much natural grassland is there in Bolivia in 2022?"
    result = await pick_land_change_dataset.coroutine(
        state={},
        tool_call_id="test-id",
        ecosystem=Ecosystem.grassland,
        measurement_type=MeasurementType.area,
        end_date="2022-12-31",
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 2
    assert ds["context_layer"] is None


async def test_buildup_no_event_returns_global_land_cover():
    # "How much built-up land is there in Canada?"
    result = await pick_land_change_dataset.coroutine(
        state={},
        tool_call_id="test-id",
        ecosystem=Ecosystem.built_up,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 1


async def test_cropland_no_event_returns_global_land_cover():
    # "Show me cropland extent in India"
    result = await pick_land_change_dataset.coroutine(
        state={},
        tool_call_id="test-id",
        ecosystem=Ecosystem.cropland,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 1


async def test_buildup_change_returns_global_land_cover():
    # "Is development expanding in Canada?"
    result = await pick_land_change_dataset.coroutine(
        state={},
        tool_call_id="test-id",
        change_type=ChangeType.change,
        ecosystem=Ecosystem.built_up,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 1


async def test_brazil_deforestation_agricultural_commodities_since_2010():
    # "Brazil deforestation linked to agricultural commodities since 2010"
    result = await pick_land_change_dataset.coroutine(
        state={},
        tool_call_id="test-id",
        ecosystem=Ecosystem.forest,
        change_type=ChangeType.loss,
        cause=Cause.agriculture,
        start_date="2010-01-01",
    )
    # TCL by Driver is aggregate (2001–2025 as one total) — can't isolate "since 2010".
    # No dataset gets a perfect score → suggestions, with TCL by Driver ranked first.
    assert result.update.get("dataset") is None
    msg = result.update["messages"][0].content
    assert "driver" in msg.lower() or "dominant" in msg.lower()


async def test_forest_loss_stays_at_tcl():
    result = await pick_land_change_dataset.coroutine(
        state={},
        tool_call_id="test-id",
        change_type=ChangeType.loss,
        ecosystem=Ecosystem.forest,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 4


# ---------------------------------------------------------------------------
# Integration tests — suggested path (no clear winner)
# ---------------------------------------------------------------------------


async def test_gain_on_grassland_returns_suggestions():
    # No grassland gain dataset — should return suggestions
    result = await pick_land_change_dataset.coroutine(
        state={},
        tool_call_id="test-id",
        change_type=ChangeType.gain,
        ecosystem=Ecosystem.grassland,
    )
    assert result.update.get("dataset") is None
    msg = result.update["messages"][0].content
    assert len(msg) > 0


async def test_loss_nonforest_returns_suggestions():
    # Loss on wetland has no direct dataset
    result = await pick_land_change_dataset.coroutine(
        state={},
        tool_call_id="test-id",
        change_type=ChangeType.loss,
        ecosystem=Ecosystem.wetland,
    )
    assert result.update.get("dataset") is None
    assert "messages" in result.update


async def test_loss_nonforest_with_cause_returns_suggestions():
    result = await pick_land_change_dataset.coroutine(
        state={},
        tool_call_id="test-id",
        change_type=ChangeType.loss,
        ecosystem=Ecosystem.wetland,
        cause=Cause.agriculture,
    )
    assert result.update.get("dataset") is None


async def test_natural_land_loss_returns_suggestions():
    result = await pick_land_change_dataset.coroutine(
        state={},
        tool_call_id="test-id",
        change_type=ChangeType.loss,
        ecosystem=Ecosystem.natural_land,
    )
    assert result.update.get("dataset") is None


async def test_buildup_annual_returns_suggestions():
    # "urbanization since 2010" — built_up + annual doesn't match any dataset perfectly
    result = await pick_land_change_dataset.coroutine(
        state={},
        tool_call_id="test-id",
        ecosystem=Ecosystem.built_up,
        temporal=Temporal.annual,
    )
    assert result.update.get("dataset") is None


async def test_disturbance_wetland_returns_suggestions_with_dist_alert_top():
    # DIST-ALERT covers wetland (score=1, not 2) so it can't be selected, but is top suggestion
    result = await pick_land_change_dataset.coroutine(
        state={},
        tool_call_id="test-id",
        change_type=ChangeType.disturbance,
        ecosystem=Ecosystem.wetland,
        cause=Cause.crop_management,
    )
    assert result.update.get("dataset") is None
    msg = result.update["messages"][0].content
    # DIST-ALERT should be the top suggestion
    assert "DIST-ALERT" in msg


async def test_carbon_nonforest_returns_suggestions_with_ghg_top():
    # Carbon + non-forest ecosystem → GHG Flux is top suggestion (eco=1, not 2)
    result = await pick_land_change_dataset.coroutine(
        state={},
        tool_call_id="test-id",
        measurement_type=MeasurementType.carbon_emissions,
        ecosystem=Ecosystem.wetland,
    )
    assert result.update.get("dataset") is None
    msg = result.update["messages"][0].content
    assert (
        "greenhouse gas" in msg.lower()
        or "GHG" in msg
        or "flux" in msg.lower()
    )


async def test_natural_land_change_returns_suggestions():
    # GLC covers natural_land as a close match (eco=1), not perfect
    result = await pick_land_change_dataset.coroutine(
        state={},
        tool_call_id="test-id",
        change_type=ChangeType.change,
        ecosystem=Ecosystem.natural_land,
    )
    assert result.update.get("dataset") is None


async def test_buildup_annual_suggestions_rank_by_relevance():
    # Urbanization + annual: topically relevant datasets should lead suggestions
    result = await pick_land_change_dataset.coroutine(
        state={},
        tool_call_id="test-id",
        ecosystem=Ecosystem.built_up,
        temporal=Temporal.annual,
    )
    assert result.update.get("dataset") is None
    msg = result.update["messages"][0].content
    # Global Land Cover (eco=2 for built_up) should appear
    assert "land cover" in msg.lower()
    # Grasslands should not appear (eco=0 for built_up)
    assert "grassland" not in msg.lower()


async def test_suggestions_contain_top_three_datasets():
    # Suggestions message should name at least two datasets
    result = await pick_land_change_dataset.coroutine(
        state={},
        tool_call_id="test-id",
        change_type=ChangeType.loss,
        ecosystem=Ecosystem.wetland,
    )
    msg = result.update["messages"][0].content
    from src.agent.datasets.config import DATASETS

    names = [ds["dataset_name"] for ds in DATASETS]
    mentioned = sum(1 for name in names if name in msg)
    assert mentioned >= 2
