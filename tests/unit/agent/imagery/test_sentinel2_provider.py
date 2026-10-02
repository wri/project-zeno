from datetime import date

from src.agent.imagery import ImageryRequest
from src.api.services.mosaic import MosaicResult
from src.shared.imagery.contract import RasterSource
from src.shared.imagery.sentinel2 import (
    SceneSummary,
    SearchWindowPeriod,
    Sentinel2Imagery,
)
from tests.unit.agent.imagery.factories import sentinel2_result_from

VAUD = {
    "name": "Vaud",
    "source": "gadm",
    "src_id": "CHE.26_1",
    "bbox": [6.0, 46.2, 7.2, 46.9],
}

MOSAIC = MosaicResult(
    mosaic_id="abc123",
    item_count=4,
    date_start=date(2025, 5, 28),
    date_end=date(2025, 6, 6),
    mean_cloud_cover=7.35,
    min_cloud_cover=2.1,
    max_cloud_cover=14.8,
)


REQUEST = ImageryRequest(
    aois=[VAUD],
    target_date=date(2025, 6, 1),
    language="en",
    window_days=7,
    max_cloud_cover=20,
)


async def imagery_built_from(mosaic: MosaicResult):
    return (await sentinel2_result_from(mosaic, REQUEST)).imagery


async def test_sentinel2_provider_builds_sentinel2_imagery_from_the_mosaic_it_searched():
    assert await imagery_built_from(MOSAIC) == Sentinel2Imagery(
        period=SearchWindowPeriod.from_search(
            date(2025, 6, 1), window_days=7, today=date.today()
        ),
        layer_id="abc123",
        tile_url=MOSAIC.tile_url,
        source=RasterSource(
            tiles=[MOSAIC.tile_url],
            bounds=(6.0, 46.2, 7.2, 46.9),
            minzoom=8,
            maxzoom=14,
        ),
        mosaic_id="abc123",
        max_cloud_cover=20,
        scenes=SceneSummary(
            item_count=4,
            start_date=date(2025, 5, 28),
            end_date=date(2025, 6, 6),
            mean_cloud_cover=7.35,
            min_cloud_cover=2.1,
            max_cloud_cover=14.8,
        ),
        aoi_names=["Vaud"],
    )


async def test_sentinel2_provider_has_no_scene_summary_when_the_mosaic_stats_are_incomplete():
    incomplete = MosaicResult(mosaic_id="abc123", item_count=1)

    assert (await imagery_built_from(incomplete)).scenes is None
