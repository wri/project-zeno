from datetime import date

from src.agent.imagery import ImageryRequest, PlanetImageryProvider
from src.shared.imagery.planet import MonthlyPeriod, PlanetImagery
from tests.unit.agent.imagery.factories import ALTAMIRA, NOVO_PROGRESSO


async def planet_layer_id(
    aois: list[dict], target_date: date = date(2026, 8, 15)
) -> str:
    request = ImageryRequest(aois=aois, target_date=target_date, language="en")
    result = await PlanetImageryProvider().get_imagery(request)
    return result.imagery.layer_id


async def test_planet_provider_builds_planet_imagery_for_the_requested_month():
    request = ImageryRequest(
        aois=[NOVO_PROGRESSO], target_date=date(2026, 8, 15), language="en"
    )

    result = await PlanetImageryProvider().get_imagery(request)

    assert result.imagery == PlanetImagery(
        period=MonthlyPeriod.from_month("2026-08"),
        layer_id=result.imagery.layer_id,
        tile_url=(
            "https://tiles.globalforestwatch.org/integrated_alerts_planet_imagery"
            "/{z}/{x}/{y}.png?month=2026-08"
        ),
        bounds=(-56.0, -8.0, -54.0, -6.0),
        min_zoom=10,
        max_zoom=18,
        aoi_names=["Novo Progresso"],
    )


async def test_planet_provider_gives_different_areas_in_the_same_month_different_layer_ids():
    novo_progresso = await planet_layer_id([NOVO_PROGRESSO])
    altamira = await planet_layer_id([ALTAMIRA])

    assert novo_progresso != altamira


async def test_planet_provider_gives_the_same_area_in_different_months_different_layer_ids():
    august = await planet_layer_id([NOVO_PROGRESSO], date(2026, 8, 15))
    september = await planet_layer_id([NOVO_PROGRESSO], date(2026, 9, 15))

    assert august != september


async def test_planet_provider_gives_the_same_layer_id_whatever_order_the_areas_come_in():
    forward = await planet_layer_id([NOVO_PROGRESSO, ALTAMIRA])
    backward = await planet_layer_id([ALTAMIRA, NOVO_PROGRESSO])

    assert forward == backward


async def test_planet_provider_gives_the_same_request_the_same_layer_id():
    first = await planet_layer_id([NOVO_PROGRESSO])
    replayed = await planet_layer_id([NOVO_PROGRESSO])

    assert first == replayed
