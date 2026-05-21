from src.agent.tools.pick_land_change_dataset import (
    Cause,
    Event,
    LandUseLandCover,
    Measurement,
    TemporalResolution,
    pick_land_change_dataset,
)


async def test_disturbance_wetland_with_cause_returns_dist_alert_driver():
    # "What peatland area was disturbed due to crop management?"
    result = await pick_land_change_dataset.coroutine(
        state={}, tool_call_id="test-id",
        event=Event.disturbance, land_cover=LandUseLandCover.wetland, cause=Cause.crop_management,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 0
    assert ds["context_layer"] == "driver"


async def test_forest_loss_annual_no_cause_returns_tcl():
    # "How much tree cover loss in Brazil in 2024?"
    result = await pick_land_change_dataset.coroutine(
        state={}, tool_call_id="test-id",
        event=Event.loss, land_cover=LandUseLandCover.forest, temporal_resolution=TemporalResolution.annual,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 4
    assert ds["context_layer"] is None


async def test_deforestation_primary_forest_returns_tcl_primary_forest():
    # "How much primary forest deforestation in DRC since 2001?"
    result = await pick_land_change_dataset.coroutine(
        state={}, tool_call_id="test-id",
        event=Event.deforestation, land_cover=LandUseLandCover.primary_forest,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 4
    assert ds["context_layer"] == "primary_forest"


async def test_forest_loss_with_wildfire_cause_returns_tcl_by_driver():
    # "Which US state lost the most forest due to wildfires?"
    result = await pick_land_change_dataset.coroutine(
        state={}, tool_call_id="test-id",
        event=Event.loss, land_cover=LandUseLandCover.forest, cause=Cause.wildfire,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 8
    assert ds["context_layer"] == "driver"


async def test_carbon_emission_forest_returns_ghg_flux():
    # "How much carbon was emitted due to tree cover loss in Indonesia?"
    result = await pick_land_change_dataset.coroutine(
        state={}, tool_call_id="test-id",
        event=Event.carbon_emission, land_cover=LandUseLandCover.forest, measurement=Measurement.co2e,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 6
    assert ds["context_layer"] is None


async def test_forest_gain_with_dates_returns_tree_cover_gain():
    # "How much tree cover was gained between 2000 and 2020 in the Amazon?"
    result = await pick_land_change_dataset.coroutine(
        state={}, tool_call_id="test-id",
        event=Event.gain, land_cover=LandUseLandCover.forest, start_date="2000-01-01", end_date="2020-12-31",
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 5
    assert ds["context_layer"] is None


async def test_land_cover_change_cropland_returns_global_land_cover():
    # "How much land changed to cropland in California in the past decade?"
    result = await pick_land_change_dataset.coroutine(
        state={}, tool_call_id="test-id",
        event=Event.change, land_cover=LandUseLandCover.cropland,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 1
    assert ds["context_layer"] is None


async def test_grassland_change_returns_grassland_dataset_not_global_land_cover():
    # "Did natural grasslands increase from 2017 to 2022 in Hwange national park?"
    result = await pick_land_change_dataset.coroutine(
        state={}, tool_call_id="test-id",
        event=Event.change, land_cover=LandUseLandCover.grasslands,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 2
    assert ds["context_layer"] is None


async def test_natural_land_aggregate_returns_sbtn():
    # "What percentage of land in Kurtjar People territory is non-natural?"
    result = await pick_land_change_dataset.coroutine(
        state={}, tool_call_id="test-id",
        land_cover=LandUseLandCover.natural_land, temporal_resolution=TemporalResolution.aggregate,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 3
    assert ds["context_layer"] is None


async def test_grasslands_area_returns_grassland_dataset():
    # "How much natural grassland is there in Bolivia in 2022?"
    result = await pick_land_change_dataset.coroutine(
        state={}, tool_call_id="test-id",
        land_cover=LandUseLandCover.grasslands, measurement=Measurement.area, end_date="2022-12-31",
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 2
    assert ds["context_layer"] is None


async def test_gain_on_grassland_stays_at_grassland_dataset():
    # No grassland gain dataset — stays at land_cover default (natural grasslands)
    result = await pick_land_change_dataset.coroutine(
        state={}, tool_call_id="test-id",
        event=Event.gain, land_cover=LandUseLandCover.grasslands,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 2


async def test_loss_nonforest_stays_at_land_cover_default():
    # Loss on wetland has no dataset — stays at SBTN Natural Lands (wetland default)
    result = await pick_land_change_dataset.coroutine(
        state={}, tool_call_id="test-id",
        event=Event.loss, land_cover=LandUseLandCover.wetland,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 3


async def test_loss_nonforest_with_cause_stays_at_land_cover_default():
    # Loss on wetland by agriculture — cause doesn't unlock a wetland-loss dataset
    result = await pick_land_change_dataset.coroutine(
        state={}, tool_call_id="test-id",
        event=Event.loss, land_cover=LandUseLandCover.wetland, cause=Cause.agriculture,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 3


async def test_carbon_nonforest_routes_to_ghg():
    # Carbon always routes to GHG flux regardless of land_cover
    result = await pick_land_change_dataset.coroutine(
        state={}, tool_call_id="test-id",
        event=Event.carbon_emission, land_cover=LandUseLandCover.wetland,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 6


# ---------------------------------------------------------------------------
# LandUseLandCover — built_up / cropland as primary land_cover
# ---------------------------------------------------------------------------

async def test_buildup_no_event_returns_global_land_cover():
    # "How much built-up land is there in Canada?"
    result = await pick_land_change_dataset.coroutine(
        state={}, tool_call_id="test-id",
        land_cover=LandUseLandCover.built_up,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 1


async def test_cropland_no_event_returns_global_land_cover():
    # "Show me cropland extent in India"
    result = await pick_land_change_dataset.coroutine(
        state={}, tool_call_id="test-id",
        land_cover=LandUseLandCover.cropland,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 1


async def test_buildup_change_returns_global_land_cover():
    # "Is development expanding in Canada?" — built_up + change → land cover transitions
    result = await pick_land_change_dataset.coroutine(
        state={}, tool_call_id="test-id",
        event=Event.change, land_cover=LandUseLandCover.built_up,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 1


async def test_natural_land_change_returns_global_land_cover():
    # "Is development expanding into natural areas in Canada?"
    result = await pick_land_change_dataset.coroutine(
        state={}, tool_call_id="test-id",
        event=Event.change, land_cover=LandUseLandCover.natural_land,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 1


async def test_natural_land_loss_stays_at_sbtn():
    # No natural land loss dataset — stays at SBTN
    result = await pick_land_change_dataset.coroutine(
        state={}, tool_call_id="test-id",
        event=Event.loss, land_cover=LandUseLandCover.natural_land,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 3


async def test_forest_loss_stays_at_tcl():
    # forest loss should still go to TCL
    result = await pick_land_change_dataset.coroutine(
        state={}, tool_call_id="test-id",
        event=Event.loss, land_cover=LandUseLandCover.forest,
    )
    ds = result.update["dataset"]
    assert ds["dataset_id"] == 4
