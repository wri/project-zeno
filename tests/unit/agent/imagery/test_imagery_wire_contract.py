import json
from datetime import date

import pytest
from langchain_core.load import dumps
from pydantic import TypeAdapter

from src.agent.imagery import (
    ImageryProviderResult,
    ImageryRequest,
    PlanetImageryProvider,
)
from src.agent.tools.show_imagery import provider_command
from src.api.services.mosaic import MosaicResult
from src.shared.imagery.planet import MonthlyPeriod, PlanetImagery
from src.shared.imagery.sentinel2 import Sentinel2Imagery
from src.shared.imagery.wire import Imagery
from tests.unit.agent.imagery.factories import sentinel2_result_from

AMAZON_AOI = {
    "name": "Novo Progresso",
    "source": "gadm",
    "src_id": "BRA.14.83_2",
    "bbox": [-56.0, -8.0, -54.0, -6.0],
}
ALTAMIRA_AOI = {
    "name": "Altamira",
    "source": "gadm",
    "src_id": "BRA.14.5_2",
    "bbox": [-55.6, -9.6, -51.6, -3.0],
}


def streamed_imagery(result: ImageryProviderResult) -> Imagery:
    update = provider_command(result, "call-1").update
    streamed = json.loads(dumps(update))
    return TypeAdapter(Imagery).validate_python(streamed["imagery"])


async def test_planet_imagery_streamed_to_the_client_satisfies_the_wire_contract():
    request = ImageryRequest(
        aois=[AMAZON_AOI], target_date=date(2026, 8, 15), language="en"
    )
    result = await PlanetImageryProvider().get_imagery(request)

    imagery = streamed_imagery(result)

    assert isinstance(imagery, PlanetImagery)
    assert imagery.period == MonthlyPeriod.from_month("2026-08")


async def test_sentinel2_imagery_streamed_to_the_client_satisfies_the_wire_contract():
    request = ImageryRequest(
        aois=[AMAZON_AOI],
        target_date=date(2025, 6, 1),
        language="en",
    )
    mosaic = MosaicResult(
        mosaic_id="abc123",
        item_count=4,
        date_start=date(2025, 5, 28),
        date_end=date(2025, 6, 6),
        mean_cloud_cover=7.35,
        min_cloud_cover=2.1,
        max_cloud_cover=14.8,
    )
    result = await sentinel2_result_from(mosaic, request)

    imagery = streamed_imagery(result)

    assert isinstance(imagery, Sentinel2Imagery)
    assert imagery.scenes is not None
    assert imagery.scenes.item_count == 4


@pytest.mark.xfail(
    strict=True, reason="Planet layer_id is a constant, so every area collides"
)
async def test_planet_imagery_for_different_areas_in_the_same_month_streams_as_different_layers():
    layer_ids = set()
    for aoi in (AMAZON_AOI, ALTAMIRA_AOI):
        request = ImageryRequest(
            aois=[aoi], target_date=date(2026, 8, 15), language="en"
        )
        result = await PlanetImageryProvider().get_imagery(request)
        layer_ids.add(streamed_imagery(result).layer_id)

    assert len(layer_ids) == 2
