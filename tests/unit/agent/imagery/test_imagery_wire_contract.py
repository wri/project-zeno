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
from src.shared.imagery.planet import MonthlyPeriod, PlanetImagery
from src.shared.imagery.sentinel2 import Sentinel2Imagery
from src.shared.imagery.wire import Imagery
from tests.unit.agent.imagery.factories import (
    ALTAMIRA,
    NOVO_PROGRESSO,
    mosaic_result,
    sentinel2_result_from,
)


def streamed_imagery(result: ImageryProviderResult) -> Imagery:
    update = provider_command(result, "call-1").update
    streamed = json.loads(dumps(update))
    return TypeAdapter(Imagery).validate_python(streamed["imagery"])


async def test_planet_imagery_streamed_to_the_client_satisfies_the_wire_contract():
    request = ImageryRequest(
        aois=[NOVO_PROGRESSO], target_date=date(2026, 8, 15), language="en"
    )
    result = await PlanetImageryProvider().get_imagery(request)

    imagery = streamed_imagery(result)

    assert isinstance(imagery, PlanetImagery)
    assert imagery.period == MonthlyPeriod.from_month("2026-08")


async def test_sentinel2_imagery_streamed_to_the_client_satisfies_the_wire_contract():
    request = ImageryRequest(
        aois=[NOVO_PROGRESSO],
        target_date=date(2025, 6, 1),
        language="en",
    )
    result = await sentinel2_result_from(mosaic_result(item_count=4), request)

    imagery = streamed_imagery(result)

    assert isinstance(imagery, Sentinel2Imagery)
    assert imagery.scenes is not None
    assert imagery.scenes.item_count == 4


async def test_planet_imagery_for_different_areas_in_the_same_month_streams_as_different_layers():
    layer_ids = set()
    for aoi in (NOVO_PROGRESSO, ALTAMIRA):
        request = ImageryRequest(
            aois=[aoi], target_date=date(2026, 8, 15), language="en"
        )
        result = await PlanetImageryProvider().get_imagery(request)
        layer_ids.add(streamed_imagery(result).layer_id)

    assert len(layer_ids) == 2


async def planet_result_for(request: ImageryRequest) -> ImageryProviderResult:
    return await PlanetImageryProvider().get_imagery(request)


async def sentinel2_result_for(
    request: ImageryRequest,
) -> ImageryProviderResult:
    return await sentinel2_result_from(mosaic_result(), request)


@pytest.mark.parametrize(
    "result_for, zooms",
    [(planet_result_for, (10, 18)), (sentinel2_result_for, (8, 14))],
    ids=["planet", "sentinel-2"],
)
async def test_imagery_streams_a_raster_source_framed_on_the_requested_areas(
    result_for, zooms
):
    request = ImageryRequest(
        aois=[NOVO_PROGRESSO, ALTAMIRA],
        target_date=date(2026, 8, 15),
        language="en",
    )

    imagery = streamed_imagery(await result_for(request))

    assert imagery.source.bounds == (-56.0, -9.6, -51.6, -3.0)
    assert (imagery.source.minzoom, imagery.source.maxzoom) == zooms
