import pytest

from src.agent.tools.pick_land_change_dataset import (
    Cause,
    Event,
    LandCover,
    LandUse,
    Measurement,
    TemporalResolution,
    pick_land_change_dataset,
)


async def test_disturbance_wetland_with_cause_returns_dist_alert_driver():
    # "What peatland area was disturbed due to crop management?"
    result = await pick_land_change_dataset.coroutine(
        state={}, tool_call_id="test-id",
        event=Event.disturbance, land_cover=LandCover.wetland, cause=Cause.crop_management,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 0
    assert ds["context_layer"] == "driver"


async def test_forest_loss_annual_no_cause_returns_tcl():
    # "How much tree cover loss in Brazil in 2024?"
    result = await pick_land_change_dataset.coroutine(
        state={}, tool_call_id="test-id",
        event=Event.loss, land_cover=LandCover.forest, temporal_resolution=TemporalResolution.annual,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 4
    assert ds["context_layer"] is None


async def test_deforestation_primary_forest_returns_tcl_primary_forest():
    # "How much primary forest deforestation in DRC since 2001?"
    result = await pick_land_change_dataset.coroutine(
        state={}, tool_call_id="test-id",
        event=Event.deforestation, land_cover=LandCover.primary_forest,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 4
    assert ds["context_layer"] == "primary_forest"


async def test_forest_loss_with_wildfire_cause_returns_tcl_by_driver():
    # "Which US state lost the most forest due to wildfires?"
    result = await pick_land_change_dataset.coroutine(
        state={}, tool_call_id="test-id",
        event=Event.loss, land_cover=LandCover.forest, cause=Cause.wildfire,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 8
    assert ds["context_layer"] == "driver"


async def test_carbon_emission_forest_returns_ghg_flux():
    # "How much carbon was emitted due to tree cover loss in Indonesia?"
    result = await pick_land_change_dataset.coroutine(
        state={}, tool_call_id="test-id",
        event=Event.carbon_emission, land_cover=LandCover.forest, measurement=Measurement.co2e,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 6
    assert ds["context_layer"] is None


async def test_forest_gain_with_dates_returns_tree_cover_gain():
    # "How much tree cover was gained between 2000 and 2020 in the Amazon?"
    result = await pick_land_change_dataset.coroutine(
        state={}, tool_call_id="test-id",
        event=Event.gain, land_cover=LandCover.forest, start_date="2000-01-01", end_date="2020-12-31",
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 5
    assert ds["context_layer"] is None


async def test_land_cover_change_croplands_returns_global_land_cover():
    # "How much land changed to cropland in California in the past decade?"
    result = await pick_land_change_dataset.coroutine(
        state={}, tool_call_id="test-id",
        event=Event.change, land_cover=LandCover.croplands,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 1
    assert ds["context_layer"] is None


async def test_grassland_change_returns_grassland_dataset_not_global_land_cover():
    # "Did natural grasslands increase from 2017 to 2022 in Hwange national park?"
    result = await pick_land_change_dataset.coroutine(
        state={}, tool_call_id="test-id",
        event=Event.change, land_cover=LandCover.grasslands,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 2
    assert ds["context_layer"] is None


async def test_natural_land_aggregate_returns_sbtn():
    # "What percentage of land in Kurtjar People territory is non-natural?"
    result = await pick_land_change_dataset.coroutine(
        state={}, tool_call_id="test-id",
        land_cover=LandCover.natural_land, temporal_resolution=TemporalResolution.aggregate,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 3
    assert ds["context_layer"] is None


async def test_grasslands_area_returns_grassland_dataset():
    # "How much natural grassland is there in Bolivia in 2022?"
    result = await pick_land_change_dataset.coroutine(
        state={}, tool_call_id="test-id",
        land_cover=LandCover.grasslands, measurement=Measurement.area, end_date="2022-12-31",
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 2
    assert ds["context_layer"] is None


async def test_gain_on_grassland_raises():
    # No dataset supports grassland gain
    with pytest.raises(ValueError):
        await pick_land_change_dataset.coroutine(
            state={}, tool_call_id="test-id",
            event=Event.gain, land_cover=LandCover.grasslands,
        )


# ---------------------------------------------------------------------------
# LandUse routing — dataset 1 (Global Land Cover)
# ---------------------------------------------------------------------------

async def test_land_use_buildup_no_event_returns_global_land_cover():
    # "How much built-up land is there in Canada?"
    result = await pick_land_change_dataset.coroutine(
        state={}, tool_call_id="test-id",
        land_use=LandUse.built_up,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 1


async def test_land_use_cropland_no_event_returns_global_land_cover():
    # "Show me cropland extent in India"
    result = await pick_land_change_dataset.coroutine(
        state={}, tool_call_id="test-id",
        land_use=LandUse.cropland,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 1


async def test_land_use_buildup_change_natural_land_returns_global_land_cover():
    # "Is development expanding into important natural areas in Canada?"
    result = await pick_land_change_dataset.coroutine(
        state={}, tool_call_id="test-id",
        event=Event.change, land_cover=LandCover.natural_land, land_use=LandUse.built_up,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 1


async def test_land_use_buildup_loss_natural_land_returns_global_land_cover():
    # "loss + natural_land would normally return None; land_use should rescue it"
    result = await pick_land_change_dataset.coroutine(
        state={}, tool_call_id="test-id",
        event=Event.loss, land_cover=LandCover.natural_land, land_use=LandUse.built_up,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 1


async def test_land_use_does_not_override_forest_loss():
    # forest loss with land_use set should still go to TCL, not global land cover
    result = await pick_land_change_dataset.coroutine(
        state={}, tool_call_id="test-id",
        event=Event.loss, land_cover=LandCover.forest, land_use=LandUse.built_up,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 4
